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

⚠️ WHY THE REPORTED RECORD FOR TWO AND THE STORED ONE FOR THE THIRD. wdtt/csqtt report what they bind in the
snapshot, so the node's own word is used. An exit's reported record carries id/device/provider/up/error and
NO dial_src, so that one reads the panel's stored value — the one it pushes to the node.

⚠️ WHAT THEY BIND IS `bind`, NOT `listen` (1.8.9 qualification PANEL-5). Since 4eec67e a WDTT / csqtt `listen` is the
host clients DIAL, and the node reports what the server binds as `bind`. Behind NAT the address clients dial is never on
the box (swg-noded turn_bind binds every address for it), so a check reading `listen` said "bound to <the NAT's
address>, which is no longer on this node" for ever while every client worked. [1] and [2] are the report of a node
older than that (no `bind`: there `listen` IS the bind).

What this drives, through the REAL `_node_issues`:
  [1] a WDTT instance bound to a departed address is named, with the address
  [2] …and a csqtt instance likewise
  [3] …and an exit whose dial_src has gone
  [4] an address the node still reports raises nothing
  [5] a hostname is never flagged — these fields take one, and it can never appear in node_ips
  [6] no reported addresses → no verdict (the node did not say; that is not evidence)
  [7] turn-proxies are NOT re-reported here — the crash-loop check owns that fault
  [8] a 1.8.9 report (`bind` beside `listen`): behind NAT (bound to every address, or to the box's own address with
      Listen on) nothing is said, nor for a bind the node cannot read; a server still bound to a departed address is
      named; a `bind` that is not a string is not read (no raise)
  [9] the node card through the real sync door and /api/state: a NAT-front node's card has no such line, and a node
      still bound to a departed address has it

Run: python3 tests/stale_bound_address_selftest.py     (0 = pass)
     --perturb       drops the check (how it shipped) — expects RED in [1], [2] and [3]
     --perturb-name  drops the _is_ip guard — expects RED in [5], the false alarm that would fire on every
                     install whose servers are bound to a domain
     --perturb-listen   judges `listen` as the bind again (PANEL-5) — expects RED in [8] and [9]
     --perturb-bindtype reads a `bind` of any type — expects RED in [8] (the strip raises: /api/state's 500)
"""
import json, os, shutil, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "--perturb": ("    for _kind, _who, _addr in _bound:", "    for _kind, _who, _addr in []:"),
    "--perturb-name": ('if _h and _h not in ("0.0.0.0", "::", "*") and nips and _is_ip(_h) and _h not in nips:',
                       'if _h and _h not in ("0.0.0.0", "::", "*") and nips and _h not in nips:'),
    "--perturb-listen": ('    _at = lambda r: r["bind"] if isinstance(r.get("bind"), str) else r.get("listen")\n',
                         '    _at = lambda r: r.get("listen")\n'),
    "--perturb-bindtype": ('    _at = lambda r: r["bind"] if isinstance(r.get("bind"), str) else r.get("listen")\n',
                           '    _at = lambda r: r["bind"] if "bind" in r else r.get("listen")\n'),
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

# ── [8] a 1.8.9 report: `listen` is what clients DIAL, `bind` what the server binds ─────────────────
print("\n[8] a 1.8.9 report: `listen` is the host clients dial, `bind` what the server binds (PANEL-5)")
PUB, PRIV = "203.0.113.9", "192.168.88.10"          # behind 1:1 NAT: clients dial PUB, the box carries PRIV
m = issues(wdtt=[{"iface": "wdtt1", "listen": PUB + ":56000", "bind": "0.0.0.0:56000"}],
           csqtt=[{"iface": "csqtt1", "listen": PUB + ":56002", "bind": "0.0.0.0:56002"}], nips=(PRIV,))
check("[8] behind NAT — what clients dial is not on the box, the node binds every address: no line", bound(m) == [], m)
m = issues(wdtt=[{"iface": "wdtt1", "listen": PUB + ":56000", "bind": PRIV + ":56000"}], nips=(PRIV,))
check("[8] …nor with Listen on, bound to the box's own address", bound(m) == [], m)
m = issues(wdtt=[{"iface": "wdtt1", "listen": PUB + ":56000", "bind": ""}], nips=(PRIV,))
check("[8] …nor when the node cannot read its bind (\"\": no env file yet) — the dial host is not judged as one", bound(m) == [], m)
m = issues(wdtt=[{"iface": "wdtt1", "listen": DEAD + ":56000", "bind": DEAD + ":56000"}],
           csqtt=[{"iface": "csqtt1", "listen": DEAD + ":56002", "bind": DEAD + ":56002"}])
check("[8] a server still BOUND to an address the box no longer has is named — WDTT and csqtt, with the address",
      len(bound(m)) == 2 and all(DEAD in x for x in bound(m)) and any("wdtt1" in x for x in bound(m))
      and any("csqtt1" in x for x in bound(m)), m)
try:
    m = issues(wdtt=[{"iface": "wdtt1", "listen": DEAD + ":56000", "bind": 5}])
    why = m
except Exception as e:                                # the strip in _node_issues: /api/state's 500 for every operator
    m, why = None, "%s: %s" % (type(e).__name__, e)
check("[8] a `bind` that is not a string (no noded sends one) is not read — judged as a node that sends none, no raise",
      m is not None and len(bound(m)) == 1 and DEAD in bound(m)[0], why)

# ── [9] the node card, through the real sync door and /api/state ──────────────────────────────────
print("\n[9] the node card: the reports through the real sync door (_snap_sanitise) and /api/state (PANEL-5)")
TMP = tempfile.mkdtemp(prefix="stale-bound-")
try:
    np_, rp = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
    json.dump({"natbox": {"name": "natbox", "ifaces": {}}, "gonebox": {"name": "gonebox", "ifaces": {}}}, open(np_, "w"))
    json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp, "w"))
    def report(ips, host, bind):                      # what a 1.8.9 node posts for one WDTT and one csqtt server
        return {"hostname": "x", "generated_at": int(time.time()), "interfaces": {}, "node_ips": list(ips),
                "node_ifaces": ["eth0"], "turn_bind_any": True,
                "wdtt": [{"iface": "wdtt1", "listen": host + ":56000", "bind": bind + ":56000", "active": True}],
                "csqtt": [{"iface": "csqtt1", "listen": host + ":56002", "bind": bind + ":56002", "active": True}]}
    snaps = {"natbox": report([PRIV], PUB, "0.0.0.0"), "gonebox": report([LIVE], DEAD, DEAD)}
    door = {k: P._snap_sanitise(s, k) for k, s in snaps.items()}
    check("[9] both reports pass the door", door == {"natbox": None, "gonebox": None}, door)
    d = {"nodes_path": np_, "roster_path": rp, "stats_dir": TMP, "fleet": {}, "panel_settings": {},
         "node_snaps": snaps, "node_seen": {k: time.time() for k in snaps}}
    P.Handler.deps = d
    code, obj = P.api("GET", "/api/state", {}, {}, d)
    card = {n.get("name"): n.get("issues") or [] for n in ((obj or {}).get("data") or {}).get("nodes") or []}
    check("[9] /api/state answers with both cards", code == 200 and set(card) == {"natbox", "gonebox"}, (code, card))
    check("[9] the NAT-front node's card: no 'bound to' line", "natbox" in card and bound(card["natbox"]) == [], card)
    check("[9] the node still bound to a departed address: both lines on its card",
          len(bound(card.get("gonebox") or [])) == 2, card)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    if FAILS:
        print("\nperturbed (%s): CAUGHT (%d red)" % (MODE, len(FAILS)))
        sys.exit(0)
    print("\nperturbed (%s): NOTHING FAILED — this gate does not test what it claims" % MODE)
    sys.exit(1)
print(("\nFAILED: " + ", ".join(FAILS)) if FAILS else "\nAll checks passed.")
sys.exit(1 if FAILS else 0)
