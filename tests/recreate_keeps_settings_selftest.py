"""Self-test — RECREATING A LOST INTERFACE MUST PUT BACK WHAT IT WAS, not the fleet defaults.

The ghost-recreate flow does NOT go through `/api/iface/recreate` (which builds its request server-side from
`iface_restore_req`). It goes through the ordinary **create** door, with a body the browser assembles from
whatever `_missing_ifaces` handed it. So every field that list omits is a field the sheet has nothing to show
— and the sheet does not then send a blank, it sends the PANEL-WIDE DEFAULT, which create writes.

MEASURED end to end against the real endpoint, on an interface an operator had tuned (port 443, MTU 1420,
DoH resolvers, keepalive 15, published as a hostname), with the body the sheet builds:

    endpoint_host   hel.sanitygate.net       ->  89.167.2.2        ← every reissued client config follows
    dns             9.9.9.9, 149.112.112.112 ->  1.1.1.1
    keepalive       15                       ->  25
    mtu             1420                     ->  1280

None of it shown on screen; the operator is told only that clients must re-import. `mtu` was found first and
the other three have exactly the same shape, so this gate asserts the RULE — nothing the panel holds about a
lost interface may be replaced by a default just because the sheet had nothing to display.

⚠️ AND THE RECREATE WAS REFUSED OUTRIGHT AT ITS OWN PORT. `_node_ports` counts a missing interface's port as
claimed — by itself — so once the sheet began pre-filling the ORIGINAL port (the fix for "an interface that
lived on 443 came back on 51821"), create answered:

    400  port 443 is already used by awg0 on this node — pick another port

naming the very interface being recreated. It fires only when `ov.listen_port` is set, i.e. when the port was
deliberate rather than inherited — the case that matters. Before that fix the sheet offered a free port, so
this was unreachable: the fix for a silent wrong answer created a hard refusal. `/api/iface/update` has always
excluded its own port; create now does too, scoped to an interface the node no longer reports.

⚠️ THIS DRIVES THE REAL ENDPOINT. The failure lives in the SEAM — `_missing_ifaces` → the sheet's body →
`api("POST", "/api/iface/create")` → the stored record — and each end is defensible alone. A fixture-fed test
of any one of them stays green while the wire carries defaults.

Run: python3 tests/recreate_keeps_settings_selftest.py      (0 = pass)
     --perturb       restores the `_lastcfg`-only field list and the panel-default AWG clobber, and expects
                     the four losses back.
     --perturb-port  removes create's own-port exclusion and expects the 400 refusal back.
     --perturb-wg    drops the `cmd == ["awg"]` guard on the carried band and expects a wg
                     interface to be handed obfuscation it must never have.
"""
import copy, importlib.machinery, importlib.util, json, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PPORT = "--perturb-port" in sys.argv
PWG = "--perturb-wg" in sys.argv
PERTURB = "--perturb" in sys.argv and not (PPORT or PWG)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()

# ⚠️ ASSERT EVERY ANCHOR BEFORE TOUCHING IT. A replacement that matches nothing leaves the tree intact and
# the run reads as a clean PASS while measuring code it never perturbed.
_EMIT = '''        out[ifn] = {"subnet": lc.get("subnet"), "listen_port": _lp,
                    "mtu": _mtu_o,
                    "address": lc.get("address"), "awg_params": _awg_o or {},
                    "endpoint_host": ov.get("endpoint_host") or "",'''
_EMIT_OLD = '''        out[ifn] = {"subnet": lc.get("subnet"), "listen_port": lc.get("listen_port"),
                    "address": lc.get("address"), "awg_params": lc.get("awg_params") or {},'''
_AWG = "        _awgput = dict(_awgprev) if _awgprev else (dict(_awgdef) if _awgdef else {})\n"
_AWGP = "        _awgprev = _prev_ov.get(\"awg_params\") if (cmd == [\"awg\"] and isinstance(_prev_ov.get(\"awg_params\"), dict)) else None\n"
_AWGP_OLD = "        _awgprev = _prev_ov.get(\"awg_params\") if isinstance(_prev_ov.get(\"awg_params\"), dict) else None\n"
_AWG_OLD = "        _awgput = dict(_awgdef) if _awgdef else {}\n"
_OWN = "_pc = _port_conflict(deps, nodes, nid, _cp, own=_own_ports)"
_OWN_OLD = "_pc = _port_conflict(deps, nodes, nid, _cp)"
for _a in (_EMIT, _AWG, _AWGP, _OWN):
    assert SRC.count(_a) == 1, "anchor missing — this run would FALSE-PASS:\n" + _a[:80]

if PERTURB:
    # ⚠️ REVERT THE WHOLE EMITTER, not just its head: `dns`/`keepalive` sit below the anchor, so leaving
    # them in place would let --perturb pass on half the fix. Cut from the head to the first key the SHIPPED
    # literal also had, which is what makes the replacement a faithful "as it was".
    SRC = re.sub(r'        out\[ifn\] = \{"subnet": lc\.get\("subnet"\), "listen_port": _lp,[\s\S]*?\n                    "public_key": blessed',
                 _EMIT_OLD + '                    "public_key": blessed', SRC, count=1)
    SRC = SRC.replace(_AWG, _AWG_OLD)
if "--perturb-wg" in sys.argv:
    SRC = SRC.replace(_AWGP, _AWGP_OLD)
if PPORT:
    SRC = SRC.replace(_OWN, _OWN_OLD)

panel = PANEL
if PERTURB or PPORT or PWG:
    _fd, panel = tempfile.mkstemp(suffix=".py", prefix="recset-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)

_l = importlib.machinery.SourceFileLoader("swgpanel", panel)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if PERTURB or PPORT or PWG:
    os.unlink(panel)
P.ev_append = lambda *a, **k: None

# hel-fresh, as the panel holds it: an interface an operator TUNED, then lost (vault reset ⇒ keyless ghost).
AWG = {"Jc": "7", "Jmin": "50", "Jmax": "1000", "S1": "68", "S2": "149",
       "H1": "1122334455", "H2": "2", "H3": "3", "H4": "4"}
OV = {"public_key": "PUB=", "endpoint_host": "hel.sanitygate.net", "mtu": 1420,
      "dns": ["9.9.9.9", "149.112.112.112"], "keepalive": 15, "listen_port": 443,
      "awg_params": dict(AWG), "egress_mode": "exit", "exit_id": "aabbccdd",
      "_lastcfg": {"subnet": "10.10.1.0/24", "listen_port": 443, "address": "10.10.1.1/24",
                   "mtu": 1420, "awg_params": dict(AWG)}}
# the panel-wide defaults the sheet falls back to for anything it was not seeded with
IDF = {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25, "awg_params": {"Jc": "1", "S1": "15"}}


def missing(ov=None, snap_ifaces=None):
    c = {"ifaces": {"awg0": copy.deepcopy(ov or OV)}}
    snap = {"interfaces": snap_ifaces or {}, "iface_key_backups": {}}
    return (P._missing_ifaces(c, snap, None) or {}).get("awg0") or {}


def sheet_body(mi, node_ips=("89.167.2.2",)):
    """The body LoadIfaceSheet posts for a ghost recreate — every field seeded from `pre`, else the default.

    ⚠️ THE SHEET SENDS ALL OF THEM, ALWAYS. That is why an unseeded field is not inert: `dns`, `mtu` and
    `keepalive` are never blank, so whatever they hold at submit time is what create records."""
    return {"node": "n1", "iface": "awg0", "protocol": "awg", "subnet": mi.get("subnet") or "",
            "endpoint_host": mi.get("endpoint_host") or (node_ips[0] if node_ips else ""),
            "listen_port": str(mi.get("listen_port") or ""),
            # ⚠️ `is not None`, NOT truthiness — mirroring iface.js's `pre.dns != null`. An empty resolver
            # list and a keepalive of 0 are both OPINIONS ("no DNS line", "no PersistentKeepalive"), and
            # `or` would spend them on the fleet default, which is the very bug this file measures.
            "dns": (", ".join(mi["dns"]) if isinstance(mi.get("dns"), list) else ", ".join(IDF["dns"])),
            "mtu": str(mi.get("mtu") or IDF["mtu"]),
            "keepalive": (str(mi["keepalive"]) if isinstance(mi.get("keepalive"), int)
                          else str(IDF["keepalive"])),
            # egressBody(AUTO) — empty strings, so create leaves the stored routing alone
            "egress_mode": "direct", "egress_node": "", "egress_ip": "", "wan_iface": ""}


def create(body, ov=None, snap_ifaces=None, idf=True):
    td = tempfile.mkdtemp(prefix="recset-")
    np_, rp_ = (os.path.join(td, f) for f in ("nodes.json", "users.json"))
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {},
                      "ifaces": {"awg0": copy.deepcopy(ov)} if ov else {}}}, open(np_, "w"))
    open(rp_, "w").write("{}\n")
    deps = {"fleet": {}, "nodes_path": np_, "roster_path": rp_,
            "panel_settings": {"interface_defaults": dict(IDF)} if idf else {},
            "panel_settings_path": os.path.join(td, "ps.json"),
            "node_snaps": {"n1": {"interfaces": snap_ifaces or {}}}}
    st, resp = P.api("POST", "/api/iface/create", "", body, deps)
    saved = json.load(open(np_))["n1"]
    # ⚠️ READ BACK THE INTERFACE THE BODY NAMED. Hardcoding "awg0" here made section [5] — which creates
    # `wg7` — read an empty create request and report a missing AWG default that was in fact present.
    # A harness that looks in the wrong place produces a finding about code that is correct.
    _if = body.get("iface")
    return st, resp, (saved.get("ifaces") or {}).get(_if) or {}, (saved.get("create") or {}).get(_if) or {}


print("[1] the panel hands the browser every setting it holds — `ov` first, `_lastcfg` second")
mi = missing()
for k, want in (("listen_port", 443), ("mtu", 1420), ("endpoint_host", "hel.sanitygate.net"),
                ("keepalive", 15), ("dns", ["9.9.9.9", "149.112.112.112"])):
    check("missing_ifaces carries `%s`" % k, mi.get(k) == want, "%r (want %r)" % (mi.get(k), want))
check("…and the AmneziaWG band", (mi.get("awg_params") or {}).get("H1") == "1122334455", mi.get("awg_params"))
# ⚠️ `ov` MUST WIN. `_lastcfg` is rebuilt from what the node last REPORTED, so a box that came back with a
# fresh interface has already overwritten it — restoring from it would faithfully rebuild the wrong thing.
# `iface_restore_req` states exactly this precedence; this function has to answer the same way.
_drift = copy.deepcopy(OV)
_drift["_lastcfg"] = dict(_drift["_lastcfg"], listen_port=51821, mtu=1280, awg_params={"Jc": "9"})
md = missing(_drift)
check("⚠️ what the PANEL owns beats what the node last reported (port)", md.get("listen_port") == 443, md.get("listen_port"))
check("⚠️ …and the MTU", md.get("mtu") == 1420, md.get("mtu"))
check("⚠️ …and the band", (md.get("awg_params") or {}).get("H1") == "1122334455", md.get("awg_params"))
check("…and it still falls back to _lastcfg when the panel owns nothing",
      missing({"public_key": "P=", "_lastcfg": dict(OV["_lastcfg"])}).get("listen_port") == 443)

print("\n[2] the recreate is ALLOWED ITS OWN PORT — the record must not refuse its own restoration")
st, resp, _ov, _req = create(sheet_body(mi), ov=OV)
check("a ghost recreated on the port it had is accepted", st == 200,
      "%s %s" % (st, (resp or {}).get("error")))
# …and the check still means something for everything else.
st2, resp2, _, _ = create(dict(sheet_body(mi), iface="wg2", subnet="10.99.0.0/24"), ov=OV)
check("…while a DIFFERENT interface asking for that port is still refused", st2 == 400,
      "%s %s" % (st2, (resp2 or {}).get("error")))
st3, resp3, _, _ = create(sheet_body(mi), ov=OV, snap_ifaces={"awg0": {"meta": {"listen_port": 443}}})
check("…and so is a create aimed at one the node reports as LIVE", st3 == 400,
      "%s %s" % (st3, (resp3 or {}).get("error")))

print("\n[3] nothing the panel held is replaced by a fleet default")
st, resp, after, req = create(sheet_body(mi), ov=OV)
assert st == 200, (st, resp)
for k, want in (("endpoint_host", "hel.sanitygate.net"), ("mtu", 1420), ("keepalive", 15),
                ("dns", ["9.9.9.9", "149.112.112.112"]), ("listen_port", 443)):
    check("`%s` survives the recreate" % k, after.get(k) == want, "%r (was %r)" % (after.get(k), want))
check("⚠️ the AmneziaWG band is not overwritten by the panel-wide default",
      (after.get("awg_params") or {}).get("H1") == "1122334455", after.get("awg_params"))
check("…and the routing the operator chose is untouched",
      after.get("egress_mode") == "exit" and after.get("exit_id") == "aabbccdd", after.get("egress_mode"))

print("\n[3b] ⚠️ an explicit OFF is not an empty box — 0 and [] are values, not absences")
# `effective_params` honours both (`isinstance(_ka, int)`, and for DNS "is there a list", not "is it
# truthy"), so an operator CAN turn keepalive off and CAN ask for no DNS line. Flattened with `or`, the
# panel hands the sheet a blank, the sheet fills it with the fleet default, and create writes 25/1.1.1.1 —
# silently re-enabling two things that were deliberately off.
OFF = dict(copy.deepcopy(OV), keepalive=0, dns=[])
mo = missing(OFF)
check("keepalive 0 reaches the browser as 0, not as absent", mo.get("keepalive") == 0, mo.get("keepalive"))
check("an empty resolver list reaches it as a list, not as absent", mo.get("dns") == [], mo.get("dns"))
st, resp, off_after, _ = create(sheet_body(mo), ov=OFF)
check("…and the recreate keeps keepalive OFF", off_after.get("keepalive") == 0, off_after.get("keepalive"))
check("…and keeps the DNS line off", off_after.get("dns") == [], off_after.get("dns"))
# …while a setting the panel never held still takes the fleet default, or the fix would just invert.
NEVER = {"public_key": "P=", "listen_port": 443, "_lastcfg": dict(OV["_lastcfg"])}
mn = missing(NEVER)
check("a setting the panel never held reads as ABSENT, not as 0", mn.get("keepalive") is None, mn.get("keepalive"))
check("…and its DNS as absent, not as an empty list", mn.get("dns") is None, mn.get("dns"))
_, _, nev_after, _ = create(sheet_body(mn), ov=NEVER)
check("…so the sheet's fleet default is what lands", nev_after.get("keepalive") == 25, nev_after.get("keepalive"))

print("\n[4] …and the NODE is told, so it builds the conf right the first time")
# The node converges to the panel's band on a later sync either way, but only if the panel still holds it —
# and a conf built from a freshly rolled band serves different obfuscation until that sync lands.
check("the create request carries the original band, not a fresh roll",
      (req.get("awg_params") or {}).get("H1") == "1122334455", req.get("awg_params"))
check("…and the original port and MTU", str(req.get("listen_port")) == "443" and str(req.get("mtu")) == "1420",
      (req.get("listen_port"), req.get("mtu")))

print("\n[5] a genuinely NEW interface still takes the fleet defaults — the fix must not invert")
nb = {"node": "n1", "iface": "wg7", "protocol": "awg", "subnet": "10.44.0.0/24", "endpoint_host": "",
      "listen_port": "51830", "dns": ", ".join(IDF["dns"]), "mtu": str(IDF["mtu"]),
      "keepalive": str(IDF["keepalive"])}
st, resp, _, nreq = create(nb, ov=None)
check("a create with no prior record is accepted", st == 200, "%s %s" % (st, (resp or {}).get("error")))
check("…and it is handed the panel-wide AWG default",
      (nreq.get("awg_params") or {}).get("Jc") == "1", nreq.get("awg_params"))

print("\n[5b] ⚠️ …and a ghost rebuilt as plain WireGuard must NOT inherit the AmneziaWG band")
# The recreate sheet lets the operator change the protocol chip. Carrying the old band into a `wg` conf is a
# shape this tree has already paid for once — see the sync loop's "NEVER from an interface the node says it
# drives with plain `wg`" note, which had to grow the same test.
_wgb = dict(sheet_body(mi), protocol="wg")
st, resp, wov, wreq = create(_wgb, ov=OV)
check("a WireGuard recreate is accepted", st == 200, "%s %s" % (st, (resp or {}).get("error")))
check("⚠️ the node is NOT handed obfuscation for a wg interface", not wreq.get("awg_params"), wreq.get("awg_params"))

print("\n[6] the browser half is wired to the same facts")
mj = open(os.path.join(ROOT, "js", "model.js"), encoding="utf-8").read()
pa = open(os.path.join(ROOT, "js", "peer-actions.js"), encoding="utf-8").read()
ij = open(os.path.join(ROOT, "js", "iface.js"), encoding="utf-8").read()
check("ghostIface carries the endpoint, DNS and keepalive", "endpoint_host: mi.endpoint_host" in mj
      and "dns: Array.isArray(mi.dns) ? mi.dns : null" in mj
      and 'keepalive: typeof mi.keepalive === "number" ? mi.keepalive : null' in mj)
check("the recreate seeds the endpoint from the saved one, node IP only as a fallback",
      "endpoint: g.endpoint_host || (nr.ips || [])[0]" in pa)
check("…and passes DNS and keepalive on", "dns: Array.isArray(g.dns) ? g.dns.join(\", \") : null" in pa
      and 'keepalive: typeof g.keepalive === "number" ? g.keepalive : null' in pa)
# ⚠️ `!= null`, not `||` — the browser half has to make the same distinction the panel half does, or an
# explicit "no DNS line" is spent on the fleet default one layer further down.
check("the DNS field prefers pre over the panel default, and keeps an explicit empty one",
      "useState(pre && pre.dns != null ? pre.dns :" in ij)
check("the keepalive field prefers pre over the panel default, and keeps an explicit 0",
      'useState(String(pre && pre.keepalive != null ? pre.keepalive :' in ij)

print()
if FAILS:
    print("FAILED: " + "; ".join(FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
