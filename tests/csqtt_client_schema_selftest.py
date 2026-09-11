#!/usr/bin/env python3
"""Self-test: a csqtt server offers no client knobs, because its link IS the whole configuration.

`csqtt://connect?v=2&host=&peer=&password=&hashes=` is everything a csqtt client is told — `csqttArtifact`
builds it from those four values and reads nothing else. So a settings panel attached to a csqtt server has
nothing true to put in it.

⚠️ AND A CLIENT FALLS BACK TO ITS NATIVE FORK'S SCHEMA WHEN NOTHING SAYS OTHERWISE. `_client_schema` maps a
client id to the fork whose author wrote it, so adding anton48's `vkturnproxy` to csqtt (it speaks csqtt
from build 364) handed a csqtt server SEVEN knobs from anton48's VK-turn transport:

    numConnections · useUDP · dnsServers · turnServerOverride · serverName · vkAuth · obfProfile

none of which csqtt has — it uses no VK relay, has no rtpopus profile to pick, and its link carries no name
field. `_CLIENT_SCHEMA_BY_FORK` is where a (fork, client) pairing says what it really takes, and the picker,
the sub encoder AND the settings-save validator all read it: these would have been shown, saved, stored, and
then ignored by the artifact builder. [[two-readers-one-grammar]]

Run: python3 tests/csqtt_client_schema_selftest.py    (0 = pass)
     --perturb  drops the override so the pairing borrows anton48's schema again, RED.
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

src = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
ANCHOR = '    "csqtt":        {"vkturnproxy": []},\n'
# ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
assert ANCHOR in src, "the csqtt schema override is not where this expects it — this run would FALSE-PASS"
if PERTURB:
    src = src.replace(ANCHOR, "", 1)

m = types.ModuleType("p")
m.__dict__.update({"__name__": "p", "__file__": os.path.join(ROOT, "swg-panel-server")})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), m.__dict__)

print("[1] every client of a csqtt server takes no settings")
clients = m._TURN_CLIENT_COMPAT.get("csqtt") or {}
check("csqtt has clients to check", len(clients) >= 2, list(clients))
for cid in clients:
    sch = m._client_schema_for("csqtt", cid)
    check("csqtt + %-12s offers nothing to configure" % cid, sch == [],
          "%d knob(s): %s" % (len(sch), ", ".join(d.get("key", "?") for d in sch)))

print("\n[2] ⚠️ …and specifically none of the VK-turn knobs it does not have")
LEAKED = ("numConnections", "useUDP", "dnsServers", "turnServerOverride", "serverName", "vkAuth", "obfProfile")
for cid in clients:
    keys = {d.get("key") for d in m._client_schema_for("csqtt", cid)}
    bad = sorted(keys & set(LEAKED))
    check("csqtt + %-12s has no VK-turn knobs" % cid, not bad, "leaked: " + ", ".join(bad))

print("\n[3] ⚠️ CONTROL: the override narrows THIS pairing only")
# A fix that emptied the client's schema everywhere would break the fork it is actually native to.
check("anton48 + vkturnproxy keeps its real schema", len(m._client_schema_for("anton48", "vkturnproxy")) >= 5,
      len(m._client_schema_for("anton48", "vkturnproxy")))
check("…and a WDTT fork still borrows it, which is correct — same wire",
      len(m._client_schema_for("amurcanov", "vkturnproxy")) >= 5,
      len(m._client_schema_for("amurcanov", "vkturnproxy")))

print("\n[4] …and an empty schema is DROPPED by the save validator, not stored blank")
# `if not sch ... continue` in the turn_client_settings validator: an empty schema means the whole client is
# skipped, so nothing meaningless can be persisted against a csqtt server even if a client posts it.
check("the validator skips a client whose schema is empty",
      'sch = {d["key"]: d for d in (_client_schema_for(fk, cid) or [])}' in src
      and "if not sch or not isinstance(osmap_in, dict):" in src)

print("\n[5] …and the link really is the whole configuration")
art = open(os.path.join(ROOT, "turn-artifacts.js"), encoding="utf-8").read()
blk = art[art.index("function csqttArtifact("):]
blk = blk[:blk.index("\n  }")]
for f in ("host", "port", "password", "hashes"):
    check("the csqtt link carries %s" % f, f in blk)
check("⚠️ …and reads no client settings at all",
      not any(k in blk for k in LEAKED), [k for k in LEAKED if k in blk])
# …and the label does not claim a single platform, now that two apps speak this link.
# ⚠️ READ THE VALUE, NOT THE FUNCTION BODY: the first version scanned the whole block and matched the words
# "Android"/"iOS" in the COMMENT explaining why the platform came out — a check that failed on its own
# rationale. [[lesson-broken-test-not-broken-code]]
import re as _re
_lab = _re.search(r'label:\s*"([^"]*)"', blk)
check("the csqtt artifact has a label", bool(_lab), blk[:120])
if _lab:
    check("…and it names no one platform", "Android" not in _lab.group(1) and "iOS" not in _lab.group(1),
          "label is %r, and both Android and iOS speak csqtt now" % _lab.group(1))
    check("…while still naming the app and the scheme it is",
          "CSQTT" in _lab.group(1) and "csqtt://" in _lab.group(1), _lab.group(1))

print("\n[6] ⚠️ …and the auto-fire rests on a REGISTERED scheme, not on a parser")
# The sub page fires `ctrl.openUri` on its own when the resolved client declares `autostart`. For a csqtt
# server on iOS that client is now VK TURN Proxy, whose autostart flag was authored for its own
# `vkturnproxy://`. Parsing a csqtt link and being handed one by the OS are different facts; the second is
# what makes the button work. Verified upstream in VKTurnProxy/project.yml (CFBundleURLSchemes lists csqtt).
# Asserted here as a NOTE in the source so the next reader does not have to re-derive it, and so a future
# client that parses without registering is a decision rather than a silent dead button.
check("the reason autostart is safe for this pairing is written down",
      "CFBundleURLSchemes" in src and "csqtt" in src.split("CFBundleURLSchemes")[1][:200],
      "nothing records that the iOS app actually registers the csqtt:// scheme")
check("…and the alternative is named for whoever hits it next",
      "autostart scoped per (fork, client)" in src)

print()
if PERTURB:
    ok = bool(FAILS)
    print(("PERTURB OK — %d checks went red: a csqtt server offers another transport's knobs again" % len(FAILS))
          if ok else "PERTURB FAILED — the override was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
