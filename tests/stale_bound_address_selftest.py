#!/usr/bin/env python3
"""Self-test: a server still BOUND to an address the box no longer has must say so.

When a provider moves a box, three kinds of record keep naming the old address and nothing revisits them:

  • WDTT   — each instance stores its own `listen` (wdtt_snapshot reports it)
  • csqtt  — the same (csqtt_snapshot reports it)
  • exits  — an imported exit stores `dial_src`, the source it dials FROM

MEASURED 2026-09-16 on a customer's box: `/etc/swg-agent/wdtt.json` still said `46.17.99.41:56000` and
`csqtt.json` said `…:56002` while the live processes had been restarted onto the new address — the records
and reality disagreed, and nothing anywhere said so. A turn-proxy in that state at least announces itself by
crash-looping (that is the flapping check, and this deliberately does NOT re-report turn proxies: two lines
about one fault is how two lists start disagreeing). The self-contained kinds and the exits have no such
tell — they simply stop working, or keep working until the next restart and then stop.

⚠️ WHY THE REPORTED RECORD FOR TWO AND THE STORED ONE FOR THE THIRD. wdtt/csqtt report their `listen` in the
snapshot, so the node's own word is used. An exit's reported record carries id/device/provider/up/error and
NO dial_src, so that one reads the panel's stored value — the one it pushes to the node.

What this drives, through the REAL `_node_issues`:
  [1] a WDTT instance bound to a departed address is named, with the address
  [2] …and a csqtt instance likewise
  [3] …and an exit whose dial_src has gone
  [4] an address the node still reports raises nothing
  [5] a hostname is never flagged — these fields take one, and it can never appear in node_ips
  [6] no reported addresses → no verdict (the node did not say; that is not evidence)
  [7] turn-proxies are NOT re-reported here — the crash-loop check owns that fault

Run: python3 tests/stale_bound_address_selftest.py     (0 = pass)
     --perturb       drops the check (how it shipped) — expects RED in [1], [2] and [3]
     --perturb-name  drops the _is_ip guard — expects RED in [5], the false alarm that would fire on every
                     install whose servers are bound to a domain
"""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb": ("    for _kind, _who, _addr in _bound:", "    for _kind, _who, _addr in []:"),
    "--perturb-name": ('if _h and _h not in ("0.0.0.0", "::", "*") and nips and _is_ip(_h) and _h not in nips:',
                       'if _h and _h not in ("0.0.0.0", "::", "*") and nips and _h not in nips:'),
}
MODE = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:200]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(PANEL, encoding="utf-8").read()
if MODE:
    cut, new = PLANTS[MODE]
    assert src.count(cut) == 1, "perturbation anchor for %s missing or not unique — would FALSE-PASS" % MODE
    src = src.replace(cut, new, 1)

P = types.ModuleType("p")
P.__dict__.update({"__name__": "p", "__file__": PANEL})
exec(compile(src.split("\nif __name__ ==")[0], "swg-panel-server", "exec"), P.__dict__)

LIVE, DEAD = "82.24.110.35", "46.17.99.41"

def issues(*, wdtt=(), csqtt=(), exits=(), turn=(), nips=(LIVE,)):
    c = {"exits": list(exits)}
    snap = {"node_ips": list(nips), "node_ifaces": [],
            "wdtt": list(wdtt), "csqtt": list(csqtt), "turn_proxies": list(turn)}
    return [str(i.get("error") or "") for i in P._node_issues(c, snap)]

def bound(msgs):
    return [m for m in msgs if "no longer on this node" in m and "is bound to" in m]

# ── [1]-[3] each kind is named ────────────────────────────────────────────────────────────────────
print("[1] a WDTT instance bound to a departed address")
m = issues(wdtt=[{"iface": "wdtt1", "listen": DEAD + ":56000"}])
check("[1] it is reported", len(bound(m)) == 1, m)
check("[1] …naming the instance and the address", any("wdtt1" in x and DEAD in x for x in bound(m)), m)

print("\n[2] a csqtt instance likewise")
m = issues(csqtt=[{"iface": "csqtt1", "listen": DEAD + ":56002"}])
check("[2] it is reported", len(bound(m)) == 1, m)
check("[2] …naming the instance and the address", any("csqtt1" in x and DEAD in x for x in bound(m)), m)

print("\n[3] an exit whose dial_src has gone")
m = issues(exits=[{"id": "51d58888", "label": "warp-1", "dial_src": DEAD}])
check("[3] it is reported", len(bound(m)) == 1, m)
check("[3] …naming the exit and the address", any("warp-1" in x and DEAD in x for x in bound(m)), m)

# ── [4] the current address is fine ───────────────────────────────────────────────────────────────
print("\n[4] an address the node still reports raises nothing")
check("[4] a live wdtt listen is silent", bound(issues(wdtt=[{"iface": "wdtt1", "listen": LIVE + ":56000"}])) == [],
      issues(wdtt=[{"iface": "wdtt1", "listen": LIVE + ":56000"}]))
check("[4] a live exit dial_src is silent", bound(issues(exits=[{"id": "x", "dial_src": LIVE}])) == [],
      issues(exits=[{"id": "x", "dial_src": LIVE}]))
check("[4] a wildcard bind is not an address that can 'go away'",
      bound(issues(wdtt=[{"iface": "wdtt1", "listen": "0.0.0.0:56000"}])) == [],
      issues(wdtt=[{"iface": "wdtt1", "listen": "0.0.0.0:56000"}]))

# ── [5] a hostname is not an address ──────────────────────────────────────────────────────────────
print("\n[5] a DNS name is never flagged")
m = issues(wdtt=[{"iface": "wdtt1", "listen": "teabata.swgpanel.com:56000"}])
check("[5] a domain listen is left alone", bound(m) == [], m)

# ── [6] no reported addresses is not evidence ─────────────────────────────────────────────────────
print("\n[6] 'the node did not say' is not 'the address is stale'")
check("[6] an empty node_ips yields no verdict",
      bound(issues(wdtt=[{"iface": "wdtt1", "listen": DEAD + ":56000"}], nips=())) == [],
      issues(wdtt=[{"iface": "wdtt1", "listen": DEAD + ":56000"}], nips=()))

# ── [7] one fault, one line ───────────────────────────────────────────────────────────────────────
print("\n[7] a turn-proxy's dead bind is the crash-loop check's to report, not this one")
m = issues(turn=[{"service": "vk-turn-proxy-WINGS-N-56004", "listen": DEAD + ":56004", "running": True}])
check("[7] this check does not also report turn-proxies", bound(m) == [], m)

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
