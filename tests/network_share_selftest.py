#!/usr/bin/env python3
"""Self-test for NETWORKS P5 — sharing (docs/NETWORKS-PLAN.md §15).

A provider with a `share` is reachable only by its owner and its grantees, per node, from sources the node can vouch
for, and the node enforces it with one prerouting table. What this holds:

 PANEL
  [1] `share_grants`: the owner always in, a lapsed date and a deleted user grant nothing, not restricted ⇒ None.
  [2] `share_clean`: the shapes; the owner never stored; a NEW past date or unknown user refused while a STORED one is
      dropped quietly; null clears.
  [3] ⚠️ through the real door: "restricted, nobody granted" survives an unrelated edit (§15.5 — a falsy share would
      silently re-open the network), a refusal says why, and null makes it open again.
  [4] S8: a restricted provider is inert `share_unsupported` on a node that cannot enforce it, owner included.
  [5] `net_share_for_node`: the owner's and grantees' deployments ON THIS NODE and the networks they carry — never a
      keyless one, a blocked user's, a lapsed grant's or another node's; deterministic; [] with nothing restricted,
      and the sync reply names the key only behind that result (D1).
  [6] the reports: the audience is owner + grantees, who is cut off is counted, a keyless grantee named; "Networks
      this user can reach" hides a network not shared with that user.
 NODE
  [7] the plan: networks from the ACL's own accepted members, never the wire; bad elements dropped; widest date kept.
  [8] the table, by packet (tests/nft_guarded_model.py): the skeleton line at `mangle - 5` exact; a grantee in, a stranger out,
      a network grantee only on its own interface; replies, IPv6 and everything outside the guard untouched; dates as timeouts —
      a lapsed one not loaded, one beyond the cap without a timeout; no concat interval set; a device name that could escape its
      quotes never reaching nft; a plan change SWAPS and the old generation is gone whole.
  [9] D1 and the restart: asked once, then nothing; a table left from before is removed.
 [10] steady state: nothing reloaded while the plan holds — including a countdown — and reloaded when a grant moves or
      a date comes within the cap.
 [11] ⚠️ fail closed (S7): a table that will not load takes the networks OUT of the ACL, own /32 kept, and says so.
 [12] a flushed table is rebuilt by the routing pass; a rebuild that fails is forgotten, so the next pass strips.
 [13] `net_deps` says the node can enforce (S8's other half), and the sync loop applies the restriction before the ACL.
 §16 — KEYLESS
 [14] a keyless grantee is a source only where its REPORTED server build vouches for its path: a capable qWDTT wire path is;
      csqtt and ildarmaga builds not in the table, ildarmaga RAW, a device never connected, a deactivated password, a stopped
      server and an ungranted user are not — each named with its reason in the report, and "Networks this user can reach"
      follows the same rule.
 [15] ⚠️ the capability table names only PUBLISHED builds (every entry is in WDTT_BUILDS / CSQTT_BUILDS) and never ildarmaga RAW.
 §16 — THE SHARED TABLE (DEVICE-ACCESS-PLAN §16)
 [16] A2 a fault inside the reconciler carries every provider the reply names for nobody, says so, and the next pass restricts
      again; nested grantee networks on one interface load, the narrower returning in the reload the wider one's lapse causes.

Hermetic. Run: python3 tests/network_share_selftest.py            (0 = pass)
     --perturb        grants a lapsed date again and expects RED on [1] and [5].
     --perturb-open   hands the ACL back UNSTRIPPED when the table will not load and expects RED on [11].
     --perturb-keyless  vouches for every keyless build and expects RED on [14].
     --perturb-swap     reloads a plan change by delete + recreate, as P5 shipped (DEVICE-ACCESS §15's leak), and expects RED on [10].
     --perturb-bare-drop  drops the guard's scope from the final rule (it would take every IPv6 packet) and expects RED on [8].
     --perturb-iface    matches a network grantee from any interface and expects RED on [8].
     --perturb-fault    removes the reconciler's own fault handler and expects RED on [16] A2.
     --perturb-nested   loads nested grantee networks as they come and expects RED on [16].
     --perturb-retry    stops declaring after a refused swap and expects RED on [16].
"""
import importlib.machinery, importlib.util, inspect, ipaddress, json, os, re, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from nft_guarded_model import Kernel, _span   # noqa: E402
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv
PERTURB_OPEN = "--perturb-open" in sys.argv
PERTURB_KEYLESS = "--perturb-keyless" in sys.argv
PERTURB_SWAP = "--perturb-swap" in sys.argv
PERTURB_BARE = "--perturb-bare-drop" in sys.argv
PERTURB_IFACE = "--perturb-iface" in sys.argv
PERTURB_FAULT = "--perturb-fault" in sys.argv
PERTURB_NESTED = "--perturb-nested" in sys.argv
PERTURB_RETRY = "--perturb-retry" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def load(name, path):
    l = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel", PANEL)
N = load("swgnoded", NODED)
CP = N.subprocess.CompletedProcess

if PERTURB:
    _sg = P.share_grants
    P.share_grants = lambda p, users, nowv, groups: _sg(p, users, 0, groups)
if PERTURB_OPEN:
    N._share_strip = lambda desired, plan: desired
if PERTURB_KEYLESS:
    P.keyless_share_capable = lambda fork, path, version: True
if PERTURB_SWAP:
    N._gtable_swap = lambda table, old_guard, guard, counters, gen, old: N._gtable_declare(table, N.SHARE_HOOK_PRI, guard, counters, gen)
if PERTURB_BARE:
    _gd = N._gtable_declare
    N._gtable_declare = lambda *a: _gd(*a).replace('ip daddr @guard counter name "gc" drop', 'counter name "gc" drop')
if PERTURB_IFACE:
    _sg = N._share_generation
    N._share_generation = lambda plan, now, g: dict(_sg(plan, now, g), lines=[re.sub(r'iifname "[^"]+" ip saddr', "ip saddr", l)
                                                                              for l in _sg(plan, now, g)["lines"]])
if PERTURB_FAULT:
    N.reconcile_net_share = lambda node_cfg, desired, share, res, now=None: N._share_converge(node_cfg, desired, share, res, now)
if PERTURB_NESTED:
    N._share_ranges = lambda items: items
if PERTURB_RETRY:
    def _no_retry(swap, declare):
        if swap is not None:
            return N.run(["nft", "-f", "-"], input_text=swap[0]), swap[1], True
        text, gen = declare()
        return N.run(["nft", "-f", "-"], input_text=text), gen, False
    N._gtable_load = _no_retry

NOW = int(time.time())
DAY = 86400
K = lambda c: c * 43 + "="
def roster():
    return {"users": {"anna": {"name": "Anna"}, "boris": {"name": "Boris"}, "carol": {"name": "Carol"},
                      "dora": {"name": "Dora", "disabled": True}},
            "peers": {
        "office": {"id": "office", "user_id": "anna", "pubkey": K("O"), "created_at": 1, "routes": ["192.168.1.0/24"],
                   "share": {"users": {"boris": NOW + DAY}},
                   "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.2", "type": "awg"}]},
        "anna-phone": {"id": "anna-phone", "user_id": "anna", "pubkey": K("A"),
                       "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.3", "type": "awg"},
                                   {"node": "n2", "iface": "awg0", "ip": "10.8.0.3", "type": "awg"}]},
        "boris-phone": {"id": "boris-phone", "user_id": "boris", "pubkey": K("B"),
                        "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.4", "type": "wg"}]},
        "boris-wdtt": {"id": "boris-wdtt", "user_id": "boris", "wdtt_password": "x",
                       "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]},
        "boris-site": {"id": "boris-site", "user_id": "boris", "pubkey": K("S"), "created_at": 2, "routes": ["192.168.7.0/24"],
                       "targets": [{"node": "n1", "iface": "wg1", "ip": "10.9.0.5", "type": "wg"}]},
        "carol-phone": {"id": "carol-phone", "user_id": "carol", "pubkey": K("C"),
                        "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.6", "type": "awg"}]},
        "dora-phone": {"id": "dora-phone", "user_id": "dora", "pubkey": K("D"),
                       "targets": [{"node": "n1", "iface": "awg0", "ip": "10.8.0.7", "type": "awg"}]},
    }}
SNAP = {"node_ips": ["203.0.113.5"], "ether_gws": {"eth0": "203.0.113.1"},
        "interfaces": {"awg0": {"meta": {"subnet": "10.8.0.0/24"}}, "wg1": {"meta": {"subnet": "10.9.0.0/24"}}},
        "net_deps": {"panel": "198.51.100.10", "resolvers": ["198.51.100.53"], "resolvers_known": True, "share": 1}}
SNAP_NO = dict(SNAP, net_deps={k: v for k, v in SNAP["net_deps"].items() if k != "share"})
R = roster()
U = R["users"]

print("\n[1] share_grants")
check("the owner (no end) and a dated grantee", P.share_grants(R["peers"]["office"], U, NOW, {}) == {"anna": 0, "boris": NOW + DAY},
      P.share_grants(R["peers"]["office"], U, NOW, {}))
check("a date that has passed grants nothing — the owner stays",
      P.share_grants(dict(R["peers"]["office"], share={"users": {"boris": NOW - 5}}), U, NOW, {}) == {"anna": 0})
check("a user that no longer exists grants nothing", P.share_grants(dict(R["peers"]["office"], share={"users": {"ghost": 0}}), U, NOW, {}) == {"anna": 0})
check("a date on the owner is ignored: the owner never lapses",
      P.share_grants(dict(R["peers"]["office"], share={"users": {"anna": NOW - 5}}), U, NOW, {}) == {"anna": 0})
check("not restricted ⇒ None (open to everyone on the node)", P.share_grants(R["peers"]["boris-site"], U, NOW, {}) is None)
check("restricted with nobody named and no owner ⇒ {} (nobody)", P.share_grants({"share": {"users": {}}}, U, NOW, {}) == {})

print("\n[2] share_clean")
office = R["peers"]["office"]
check("null clears", P.share_clean(R, office, None, NOW) == (None, None))
check("owner-only is {'users': {}} — truthy, so it survives the preserve loop",
      P.share_clean(R, office, {}, NOW) == ({"users": {}}, None) and bool({"users": {}}))
check("the owner is never stored as a grantee", P.share_clean(R, office, {"users": {"anna": 0, "boris": 0}}, NOW) == ({"users": {"boris": 0}}, None))
for raw, tok in (([], "bad_shape"), ({"boris": 0}, "bad_shape"), ({"users": []}, "bad_shape"),
                 ({"users": {"boris": "soon"}}, "bad_date"), ({"users": {"boris": True}}, "bad_date"), ({"users": {"boris": -1}}, "bad_date"),
                 ({"users": {"ghost": 0}}, "unknown_user"), ({"users": {"boris": NOW - 60}}, "date_passed")):
    check("refused %-32s → %s" % (json.dumps(raw), tok), P.share_clean(R, office, raw, NOW) == (None, tok), P.share_clean(R, office, raw, NOW))
stored = dict(office, share={"users": {"ghost": 7, "boris": NOW - 60, "carol": 0}})
check("a STORED lapsed grant and a STORED deleted user are dropped quietly — the sheet can save back what it showed",
      P.share_clean(R, stored, {"users": {"ghost": 7, "boris": NOW - 60, "carol": 0}}, NOW) == ({"users": {"carol": 0}}, None))
many = dict(R, users=dict(U, **{"u%d" % i: {} for i in range(P.NET_SHARE_MAX + 1)}))
check("more grantees than the cap is refused", P.share_clean(many, office, {"users": {"u%d" % i: 0 for i in range(P.NET_SHARE_MAX + 1)}}, NOW) == (None, "too_many"))

print("\n[3] through the real door")
TMP = tempfile.mkdtemp(prefix="netshare-")
nodes_path, roster_path = os.path.join(TMP, "nodes.json"), os.path.join(TMP, "users.json")
json.dump({"n1": {"id": "n1", "name": "home"}}, open(nodes_path, "w"))
RD = roster(); RD["version"] = P.ROSTER_VERSION
json.dump(RD, open(roster_path, "w"))
deps = {"nodes_path": nodes_path, "roster_path": roster_path, "node_snaps": {"n1": SNAP}, "stats_dir": TMP, "fleet": {}}
def peer_now(pid):
    return json.load(open(roster_path))["peers"][pid]
try:
    c1, b1 = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "share": {"users": {}}}, deps)
    check("owner-only saved, and the save answers with the report", c1 == 200 and peer_now("office").get("share") == {"users": {}}
          and "networks" in b1, (c1, b1))
    c2, _ = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "title": "Office router"}, deps)
    check("⚠️ an unrelated edit keeps 'restricted, nobody granted' — the network does not silently re-open",
          c2 == 200 and peer_now("office").get("share") == {"users": {}}, peer_now("office"))
    c3, b3 = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "share": {"users": {"ghost": 0}}}, deps)
    check("a refusal says why, as a token, and changes nothing", c3 == 400 and b3.get("why") == "unknown_user"
          and peer_now("office").get("share") == {"users": {}}, (c3, b3))
    c4, b4 = P.api("POST", "/api/peers/networks", {}, {"peer_id": "office", "share": None}, deps)
    check("the draft preview judges a share without saving it", c4 == 200 and b4["data"].get("share") is None
          and peer_now("office").get("share") == {"users": {}}, (c4, b4))
    c5, _ = P.api("POST", "/api/peers/update", {}, {"peer_id": "office", "share": None}, deps)
    check("null makes it open again — the key is gone", c5 == 200 and "share" not in peer_now("office"), peer_now("office"))
except Exception as e:
    check("the /api/peers/update round trip ran", False, repr(e))

print("\n[4] S8 — a node that cannot enforce a restriction does not carry it")
nn_old = P.node_networks(R, "n1", SNAP_NO)
check("restricted provider on a node without net_deps.share: inert share_unsupported",
      "office" not in nn_old["carry"] and nn_old["inert"].get("office", {}).get("192.168.1.0/24", {}).get("why") == "share_unsupported", nn_old)
check("…while an open provider on that node is carried as before", "boris-site" in nn_old["carry"], nn_old)
nn = P.node_networks(R, "n1", SNAP)
check("on a node that enforces, the restricted provider is carried", nn["carry"].get("office", {}).get("nets") == ["192.168.1.0/24"], nn)
check("the desired set for an old node carries no network for it (owner included)",
      all(x["allowed_ips"] == "10.8.0.2/32" for x in P.desired_for_node(R, "n1", SNAP_NO)["awg0"] if x["public_key"] == K("O")))

print("\n[5] net_share_for_node")
ns = P.net_share_for_node(R, "n1", nn["carry"])
WANT = [{"peer": K("O"), "from": [["awg0", "10.8.0.2/32", 0], ["awg0", "10.8.0.3/32", 0], ["awg0", "192.168.1.0/24", 0],
                                  ["wg1", "10.9.0.4/32", NOW + DAY], ["wg1", "10.9.0.5/32", NOW + DAY], ["wg1", "192.168.7.0/24", NOW + DAY]]}]
check("owner's and grantee's deployments on THIS node, plus the networks they carry here — nobody else's", ns == WANT, ns)
check("never keyless, blocked, ungranted or another node's", not any(e[1] in ("10.8.0.6/32", "10.8.0.7/32") for e in ns[0]["from"]))
RL = roster(); RL["peers"]["office"]["share"] = {"users": {"boris": NOW - 5}}
nsl = P.net_share_for_node(RL, "n1", P.node_networks(RL, "n1", SNAP)["carry"])
check("a lapsed grant is gone from the reply", [e[1] for e in nsl[0]["from"]] == ["10.8.0.2/32", "10.8.0.3/32", "192.168.1.0/24"], nsl)
RO = roster(); RO["peers"]["office"]["share"] = {"users": {}}; RO["peers"]["office"]["user_id"] = None
check("owner-less, nobody granted: the provider is still listed, with no source — nobody reaches it",
      P.net_share_for_node(RO, "n1", P.node_networks(RO, "n1", SNAP)["carry"]) == [{"peer": K("O"), "from": []}])
RN = roster(); del RN["peers"]["office"]["share"]
check("nothing restricted ⇒ []", P.net_share_for_node(RN, "n1", P.node_networks(RN, "n1", SNAP)["carry"]) == [])
check("deterministic", P.net_share_for_node(R, "n1", nn["carry"]) == ns)
_psrc = open(PANEL).read()
check("the sync reply names `net_share` exactly once, behind that result",
      _psrc.count('"net_share":') == 1 and '**({"net_share": _nshare} if _nshare else {})' in _psrc)
check("…and computes it only when some peer restricts a network",
      '_share_any = _routes_any and any(q.get("routes") and net_restricted(q) for q in _peers_all)' in _psrc
      and '_nshare = net_share_for_node(roster, nid, _carry, snap) if _share_any else []' in _psrc
      and '_routes_any = snap is not None and any(q.get("routes") for q in _peers_all)' in _psrc)

# ⚠️ "RESTRICTED" IS NOT "HAS A STORED SHARE". That was the question every reader in front of share_grants asked, and it is
# right only while a share is the sole way to be restricted. Private is the other way — and the common one, because the
# switch posts {peer_id, private} alone and the Networks window hides the audience control for a private device, so
# NOTHING IN THE PRODUCT can give it a share. A private provider therefore answered "not restricted" here, and its
# networks were served to the whole node while the panel and the subscription page both said "its owner alone".
RP = roster()
del RP["peers"]["office"]["share"]                       # no stored share anywhere — the only reason to restrict is the flag
RP["peers"]["office"]["private"] = True
_cp = P.node_networks(RP, "n1", SNAP)["carry"]
check("⚠️ a PRIVATE provider with no stored share is restricted — it used to be served to the whole node",
      P.net_restricted(RP["peers"]["office"]) is True and "office" in _cp, (P.net_restricted(RP["peers"]["office"]), _cp))
_nsp = [e for e in P.net_share_for_node(RP, "n1", _cp, SNAP) if e["peer"] == K("O")]
# ⚠️ Indexed through a default. Under the perturbation that reverts this fix the list is EMPTY, and `_nsp[0]` raised —
# which aborts the gate before its summary instead of reporting a red, and a harness that crashes reports nothing at all.
_from = lambda rows: sorted(e[1] for e in (rows[0]["from"] if rows else []))
check("…and the node is told to serve it to its owner's OWN devices — both of Anna's, and the network itself",
      _from(_nsp) == ["10.8.0.2/32", "10.8.0.3/32", "192.168.1.0/24"], _nsp)
check("…and nobody else's device is a source: not Boris's, not Carol's",
      bool(_nsp) and not ({"10.9.0.4/32", "10.8.0.6/32"} & set(_from(_nsp))), _nsp)
# The precedence, proven where it is ENFORCED rather than only where it is decided: keep the live grant to Boris and make
# the device private. share_grants answers the owner alone, and the wire has to say the same.
RB = roster()
RB["peers"]["office"]["private"] = True                  # share {"users": {"boris": NOW + DAY}} left in place
_nsb = [e for e in P.net_share_for_node(RB, "n1", P.node_networks(RB, "n1", SNAP)["carry"], SNAP) if e["peer"] == K("O")]
check("⚠️ private outranks a LIVE grant on the wire, not just in share_grants — Boris was a source, and is not",
      "10.9.0.4/32" in set(_from(ns)) and bool(_nsb) and "10.9.0.4/32" not in set(_from(_nsb)),
      (ns[0]["from"] if ns else None, _nsb[0]["from"] if _nsb else None))
check("a provider that is neither private nor shared is still unrestricted — nothing else moved",
      P.net_restricted(RN["peers"]["office"]) is False, P.net_restricted(RN["peers"]["office"]))
# The other half of the same mistake: a node too old to enforce sharing HOLDS a restricted network back rather than
# carrying it open. Private was carried open there while a shared one was held — private treated as the LESSER
# restriction, which is exactly backwards.
_OLDSNAP = json.loads(json.dumps(SNAP))
_OLDSNAP["net_deps"].pop("share", None)
check("⚠️ a node that cannot enforce sharing holds a PRIVATE network back instead of carrying it open",
      "office" not in P.node_networks(RP, "n1", _OLDSNAP)["carry"]
      and (P.node_networks(RP, "n1", _OLDSNAP)["inert"].get("office") or {}).get("192.168.1.0/24", {}).get("why") == "share_unsupported",
      P.node_networks(RP, "n1", _OLDSNAP))
check("…while an unrestricted network on that same old node is still carried, as it always was",
      "boris-site" in P.node_networks(RP, "n1", _OLDSNAP)["carry"], P.node_networks(RP, "n1", _OLDSNAP)["carry"])

print("\n[6] the reports")
rep = P.network_report(R, "office", {"n1": dict(SNAP, net_share={"ok": True, "peers": [K("O")]})})
t1 = next(e for e in rep["targets"] if e["node"] == "n1")
check("the audience is owner + grantee devices that can reach it (keyless not counted)",
      t1["audience"] == {"peers": 3, "users": 2}, t1["audience"])
sh = t1.get("share") or {}
check("each grant with its devices here — a keyless one named", sh.get("grants") == [
      {"user_id": "anna", "until": 0, "owner": True, "devices": 1, "keyless": 0, "keyless_why": {}},
      {"user_id": "boris", "until": NOW + DAY, "owner": False, "devices": 2, "keyless": 1, "keyless_why": {"not_reported": 1}}], sh.get("grants"))
check("who it cuts off on the node (a blocked user is nobody)", sh.get("cut_off") == {"peers": 1, "users": 1, "providers": []}, sh.get("cut_off"))
check("what the node says about enforcing it", sh.get("node") == {"ok": True, "peers": [K("O")]}, sh.get("node"))
repn = P.network_report(RN, "office", {"n1": SNAP})
check("an open provider: the whole node, as before, and no share block",
      next(e for e in repn["targets"] if e["node"] == "n1")["audience"] == {"peers": 5, "users": 3}
      and "share" not in next(e for e in repn["targets"] if e["node"] == "n1"), repn)
un = P.user_networks(R, "carol", {"n1": SNAP})
check("carol can reach boris's open site, not anna's restricted office",
      [n["prefix"] for pr in un["peers"] for t in pr["targets"] for n in t["networks"]] == ["192.168.7.0/24"], un)
ub = P.user_networks(R, "boris", {"n1": SNAP})
bp = next(pr for pr in ub["peers"] if pr["peer_id"] == "boris-phone")["targets"][0]["networks"]
bw = next(pr for pr in ub["peers"] if pr["peer_id"] == "boris-wdtt")["targets"][0]["networks"]
check("boris's phone reaches the office, marked restricted with his date",
      any(n["prefix"] == "192.168.1.0/24" and n.get("restricted") and n.get("until") == NOW + DAY for n in bp), bp)
check("…his keyless device does not", not any(n["prefix"] == "192.168.1.0/24" for n in bw), bw)

print("\n[7] the node's plan")
NT = tempfile.mkdtemp(prefix="netshare-node-")
def conf(name, addr):
    p = os.path.join(NT, name + ".conf")
    with open(p, "w") as f:
        f.write("[Interface]\nAddress = %s\n" % addr)
    return p
CFG = {"interfaces": {"awg0": {"conf": conf("awg0", "10.8.0.1/24")}, "wg1": {"conf": conf("wg1", "10.9.0.1/24")}}}
DESIRED = {"awg0": [{"public_key": K("O"), "allowed_ips": "10.8.0.2/32,192.168.1.0/24", "preshared_key": "none", "name": "o"},
                    {"public_key": K("A"), "allowed_ips": "10.8.0.3/32", "preshared_key": "none", "name": "a"}],
           "wg1": [{"public_key": K("S"), "allowed_ips": "10.9.0.5/32,192.168.7.0/24", "preshared_key": "none", "name": "s"}]}
SHARE = [{"peer": K("O"), "nets": ["10.66.0.0/16"],
          "from": [["awg0", "10.8.0.3/32", 5], ["awg0", "10.8.0.3", 0], ["wg1", "10.9.0.4/32", NOW + 3600],
                   ["wg1", "192.168.7.0/24", NOW + 30 * DAY], ['bad"name', "10.1.0.0/24", 0], ["awg0", "garbage", 0],
                   ["awg0", "10.8.0.9/32", NOW - 5], ["awg0", "10.8.0.10/32", True], "junk"]},
         {"peer": K("Z"), "from": [["awg0", "10.8.0.3/32", 0]]}]
plan = N._share_plan(CFG, DESIRED, SHARE)
check("networks from the ACL's own accepted member — the wire's `nets` ignored; a provider carrying nothing left out",
      len(plan) == 1 and plan[0][0] == K("O") and plan[0][1] == ["192.168.1.0/24"], plan)
check("bad elements dropped; one source twice keeps the widest date (0); the lapsed one kept for the loader to omit",
      plan[0][2] == [("awg0", "10.8.0.3/32", 0), ("awg0", "10.8.0.9/32", NOW - 5), ("wg1", "10.9.0.4/32", NOW + 3600),
                     ("wg1", "192.168.7.0/24", NOW + 30 * DAY)], plan[0][2])

CALLS = []
def fresh():
    N._SHARE.update(probed=False, installed=False, sig=None, plan=None, status=None, declared=False, gen="a", names=None)
    del CALLS[:]
def res():
    return {"changed": 0, "errors": []}
SH = "swg_share"
DECLARE = "table inet swg_share\ndelete table inet swg_share\ntable inet swg_share {"
def spk(iif, saddr, daddr, **kw):
    return KS.m.packet(SH, iif, saddr, daddr, **kw)[0]

print("\n[8] the table, by packet (DEVICE-ACCESS §15, §16)")
fresh(); KS = Kernel(); N.run = KS
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
rs = KS.loads[-1] if KS.loads else ""
TS = KS.m.tables.get(SH) or {"sets": {}, "maps": {}, "chains": {}, "counters": {}}
check("DECLARED: created then deleted then declared — one load", rs.startswith(DECLARE), rs[:80])
check("⚠️ the skeleton at mangle - 5 (§15.2 S4): replies accepted first, the guard before the one vmap, a miss INSIDE the guard "
      "dropped — never a bare drop, which took every IPv6 packet",
      'chain pre { type filter hook prerouting priority mangle - 5; policy accept; ct direction reply accept; '
      'ip daddr != @guard accept; jump sel; ip daddr @guard counter name "gc" drop; }' in rs, rs)
check("the guard holds exactly the restricted networks", sorted((x["lo"], x["hi"]) for x in TS["sets"].get("guard", {}).get("els", [])) == [_span("192.168.1.0/24")])
check("a grantee reaches the network; a stranger on the same interface does not",
      spk("awg0", "10.8.0.3", "192.168.1.5") == "accept" and spk("awg0", "10.8.0.6", "192.168.1.5") == "drop")
check("⚠️ a network grantee reaches it only arriving on its own interface (§16 C2)",
      spk("wg1", "192.168.7.20", "192.168.1.5") == "accept" and spk("awg0", "192.168.7.20", "192.168.1.5") == "drop")
check("⚠️ replies, IPv6 and everything outside the guard are never touched",
      spk("awg0", "10.8.0.6", "192.168.1.5", reply=True) == "accept" and KS.m.packet(SH, "awg0", "", "", v6=True)[0] == "accept"
      and spk("awg0", "10.8.0.6", "192.168.2.5") == "accept")
check("no end ⇒ no timeout; within the cap ⇒ its remaining time; beyond the cap ⇒ no timeout; lapsed ⇒ not loaded",
      spk("awg0", "10.8.0.3", "192.168.1.5", at=10 ** 8) == "accept" and spk("wg1", "10.9.0.4", "192.168.1.5", at=3599) == "accept"
      and spk("wg1", "10.9.0.4", "192.168.1.5", at=3600) == "drop" and spk("wg1", "192.168.7.20", "192.168.1.5", at=10 ** 8) == "accept"
      and spk("awg0", "10.8.0.9", "192.168.1.5") == "drop")
check("⚠️ grantees in a HASH set with timeouts and plain per-interface sets — no concat interval set (~0.32 MiB each however small)",
      bool(TS["sets"]) and not any("interval" in s["flags"] for s in TS["sets"].values() if s["type"] == "ifname . ipv4_addr")
      and any(n != "guard" and s["type"] == "ipv4_addr" for n, s in TS["sets"].items()), {n: (s["type"], sorted(s["flags"])) for n, s in TS["sets"].items()})
check("a device name that could escape its quotes never reaches nft", 'bad"name' not in rs and "garbage" not in rs)
fresh(); KS = Kernel(); N.run = KS
N.reconcile_net_share(CFG, DESIRED, [{"peer": K("O"), "from": []}], res(), now=NOW)
check("nobody allowed ⇒ the network drops everyone", SH in KS.m.tables and spk("awg0", "10.8.0.3", "192.168.1.5") == "drop")
fresh(); KS = Kernel(); N.run = KS
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
D2 = json.loads(json.dumps(DESIRED)); D2["awg0"][0]["allowed_ips"] += ",192.168.9.0/24"
out = N.reconcile_net_share(CFG, D2, SHARE, res(), now=NOW)
_sw = KS.loads[-1]
_names = {n for k in ("sets", "maps", "chains") for n in (KS.m.tables.get(SH) or {}).get(k, {})}
check("SWAP: no delete table; the guard gains the new network; `sel` repointed to generation b",
      len(KS.loads) == 2 and "delete table" not in _sw and _sw.startswith("table inet swg_share {")
      and sorted((x["lo"], x["hi"]) for x in KS.m.tables[SH]["sets"]["guard"]["els"]) == sorted([_span("192.168.1.0/24"), _span("192.168.9.0/24")])
      and "flush chain inet swg_share sel\nadd rule inet swg_share sel ip daddr vmap @nets_b" in _sw, _sw[:200])
check("…the old generation gone whole, in an order the kernel accepted, and the new network restricted at once",
      not any(n.endswith("_a") for n in _names) and not KS.last_refused and out is D2
      and spk("awg0", "10.8.0.6", "192.168.9.5") == "drop" and spk("awg0", "10.8.0.3", "192.168.9.5") == "accept", sorted(_names))

def stub(rc=None):
    rc = rc or {}
    def run(a, input_text=None, timeout=20):
        CALLS.append((list(a), input_text))
        key = ("list" if a[:3] in (["nft", "list", "table"], ["nft", "list", "chain"]) else "delete" if a[:3] == ["nft", "delete", "table"]
               else "load" if a[:2] == ["nft", "-f"] else "other")
        # a chain that is there lists its skeleton rule — or, with `list_out`, what the test says is left in it
        out = rc.get("list_out", "ct direction reply accept\nip daddr != @guard accept\njump sel\nip daddr @guard counter name \"gc\" drop\n") \
            if a[:3] == ["nft", "list", "chain"] and not rc.get("list") else ""
        return CP(a, rc.get(key, 0), out, rc.get(key + "_err", ""))
    N.run = run

print("\n[9] D1 and the restart")
fresh(); stub({"list": 1})
r = res()
out = N.reconcile_net_share(CFG, DESIRED, None, r)
check("nothing restricted: the SAME object back, no status", out is DESIRED and N._SHARE["status"] is None)
check("…the kernel asked exactly once", [c[0] for c in CALLS] == [["nft", "list", "table", "inet", "swg_share"]], CALLS)
del CALLS[:]
for sh_ in (None, [], [{"peer": K("Z"), "from": []}]):
    N.reconcile_net_share(CFG, DESIRED, sh_, r)
check("every later pass — and a share for a provider this node does not carry — NO subprocess", CALLS == [], CALLS)
fresh(); stub({"list": 0})
N.reconcile_net_share(CFG, DESIRED, None, res())
check("RESTART: a table left from before is found and removed — a lifted restriction does not keep dropping",
      ["nft", "delete", "table", "inet", "swg_share"] in [c[0] for c in CALLS] and not N._SHARE["installed"], CALLS)

print("\n[10] steady state")
fresh(); stub({"list": 1})
r = res()
out = N.reconcile_net_share(CFG, DESIRED, SHARE, r, now=NOW)
loads = [c for c in CALLS if c[0][:2] == ["nft", "-f"]]
check("installed with one load, the ACL untouched (same object), status in force",
      len(loads) == 1 and out is DESIRED and N._SHARE["status"] == {"ok": True, "peers": [K("O")]}, (loads, N._SHARE["status"]))
del CALLS[:]; stub({"list": 0})
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW + 600)
check("ten minutes later, same plan: nothing forked — a countdown never reloads", CALLS == [], CALLS)
S2 = json.loads(json.dumps(SHARE)); S2[0]["from"].append(["awg0", "10.8.0.11/32", 0])
N.reconcile_net_share(CFG, DESIRED, S2, res(), now=NOW + 600)
_sl = [c for c in CALLS if c[0][:2] == ["nft", "-f"]]
check("⚠️ a new grantee reloads — by a SWAP: no delete table, generation b", len(_sl) == 1 and "delete table" not in _sl[0][1]
      and N._SHARE["gen"] == "b", [c[1][:80] for c in _sl])
del CALLS[:]
near = NOW + 30 * DAY - N.SHARE_TIMEOUT_CAP + 60
N.reconcile_net_share(CFG, DESIRED, S2, res(), now=near)
nl = [c for c in CALLS if c[0][:2] == ["nft", "-f"]]
check("a date coming within the cap reloads once, now with its timeout",
      len(nl) == 1 and "192.168.7.0/24 timeout %ds" % (NOW + 30 * DAY - near) in nl[0][1], nl)
del CALLS[:]
N.reconcile_net_share(CFG, DESIRED, S2, res(), now=near + 300)
check("…and not again", CALLS == [], CALLS)

print("\n[11] fail closed")
fresh(); stub({"list": 1, "load": 1, "load_err": "Error: Could not process rule: Numerical result out of range"})
r = res()
before = json.dumps(DESIRED)
out = N.reconcile_net_share(CFG, DESIRED, SHARE, r, now=NOW)
o = next(x for x in out["awg0"] if x["public_key"] == K("O"))
check("⚠️ the restricted provider's network is OUT of the ACL — carried for nobody, never open to everyone",
      o["allowed_ips"] == "10.8.0.2/32", o)
check("…its own tunnel address kept, and an open provider untouched", out["wg1"] == DESIRED["wg1"] and
      next(x for x in out["awg0"] if x["public_key"] == K("A")) == DESIRED["awg0"][1], out)
check("…the given set not modified in place", json.dumps(DESIRED) == before)
st = N._SHARE["status"] or {}
check("…and it says why", st.get("ok") is False and st.get("why") == "nft_failed" and "out of range" in st.get("detail", "")
      and r["errors"] and N._SHARE["probed"] is False, (st, r))

fresh(); stub({"list": 1})
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
del CALLS[:]; stub({"list": 0, "load": 1, "load_err": "Error: interval overlaps with an existing one"})
r = res()
out = N.reconcile_net_share(CFG, DESIRED, S2, r, now=NOW)
check("⚠️ a refused SWAP strips too — the previous table enforces the previous plan, so the new one is not in force (§15.2)",
      next(x for x in out["awg0"] if x["public_key"] == K("O"))["allowed_ips"] == "10.8.0.2/32" and N._SHARE["declared"] is False, out)
del CALLS[:]; stub({"list": 0})
out = N.reconcile_net_share(CFG, DESIRED, S2, res(), now=NOW)
_dl = [c for c in CALLS if c[0][:2] == ["nft", "-f"]]
check("…and the next pass DECLARES, carrying the network again", len(_dl) == 1 and _dl[0][1].startswith("table inet swg_share\ndelete table")
      and out is DESIRED, [c[1][:60] for c in _dl])

print("\n[12] a flushed table")
fresh(); stub({"list": 1})
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
del CALLS[:]; stub({"list": 1})
r = res()
N.net_share_verify(r, now=NOW + 30)
check("the routing pass finds it gone and rebuilds it", any(c[0][:2] == ["nft", "-f"] for c in CALLS) and r["changed"] == 1, CALLS)
del CALLS[:]; stub({"list": 0})
N.net_share_verify(res())
check("present: ONE chain listed (not the whole table), not rebuilt", [c[0][:5] for c in CALLS] == [["nft", "list", "chain", "inet", "swg_share"]], CALLS)
# ⚠️ `nft flush table` keeps the table, its sets and its chains, and empties the chains (measured on swgt, 1.8.7 §D4): named, it
# restricts nothing.
del CALLS[:]; stub({"list": 0, "list_out": ""})
r = res()
N.net_share_verify(r, now=NOW + 60)
check("⚠️ a table standing but EMPTIED is declared again, not read as present", any(c[0][:2] == ["nft", "-f"] for c in CALLS) and r["changed"] == 1, CALLS)
del CALLS[:]; stub({"list": 1, "load": 1})
r = res()
N.net_share_verify(r)
check("a rebuild that fails is forgotten and said", N._SHARE["installed"] is False and N._SHARE["sig"] is None and r["errors"], (N._SHARE, r))
stub({"list": 1, "load": 1})
out = N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW + 60)
check("…so the next reply pass strips the network instead of leaving it open",
      next(x for x in out["awg0"] if x["public_key"] == K("O"))["allowed_ips"] == "10.8.0.2/32", out)
fresh()
N.reconcile_net_share(CFG, DESIRED, None, res())
del CALLS[:]
N.net_share_verify(res())
check("nothing restricted: the routing pass forks nothing", CALLS == [], CALLS)

print("\n[13] the node says it can enforce, and restricts before the ACL")
N._resolvers = lambda: (["198.51.100.53"], True)
check("net_deps carries share: 1", N.net_deps().get("share") == 1, N.net_deps())
_nsrc = open(NODED).read()
check("the sync loop hands `reconcile` what reconcile_net_share returns, after net_filter_desired",
      "r = reconcile(node_cfg, reconcile_net_share(node_cfg, net_filter_desired(node_cfg, reply[\"desired\"])," in _nsrc)
_bs = inspect.getsource(N.build_snapshot)
check("the snapshot adds `net_share` only under a status", 'if _SHARE["status"]:' in _bs and 'snap["net_share"] = dict(_SHARE["status"])' in _bs
      and _bs.count('"net_share"') == 1)

print("\n[14] §16 — keyless grantees")
RK = roster()
RK["peers"]["boris-wdtt"]["targets"] = [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]
RK["peers"]["boris-csq"] = {"id": "boris-csq", "user_id": "boris", "csqtt_password": "cpw",
                            "targets": [{"node": "n1", "iface": "csqtt1", "type": "csqtt"}]}
RK["peers"]["anna-ild"] = {"id": "anna-ild", "user_id": "anna", "wdtt_password": "ipw", "targets": [{"node": "n1", "iface": "wdtt2", "type": "wdtt"}]}
RK["peers"]["anna-new"] = {"id": "anna-new", "user_id": "anna", "wdtt_password": "npw", "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]}
RK["peers"]["carol-wdtt"] = {"id": "carol-wdtt", "user_id": "carol", "wdtt_password": "cw", "targets": [{"node": "n1", "iface": "wdtt1", "type": "wdtt"}]}
def sk(**over):
    q = {"iface": "wdtt1", "fork": "qwdtt", "version": "1.4.3", "active": "active", "raw_iface": "wdttraw1",
         "passwords": {"x": {"ip": "10.66.66.2", "raw_ip": "10.70.66.2"}, "npw": {"ip": "", "raw_ip": ""}, "cw": {"ip": "10.66.66.9"}}}
    q.update(over)
    return dict(SNAP, wdtt=[q, {"iface": "wdtt2", "fork": "ildarmaga", "version": "1.5.40-2", "active": "active", "raw_iface": "wdttraw2",
                                "passwords": {"ipw": {"ip": "10.66.67.3", "raw_ip": "10.70.67.3"}}}],
                csqtt=[{"iface": "csqtt1", "fork": "csqtt", "version": "2.1.9", "active": "active", "passwords": {"cpw": {"ip": "10.66.68.4"}}}])
SK = sk()
nk = P.net_share_for_node(RK, "n1", P.node_networks(RK, "n1", SK)["carry"], SK)
els = {(e[0], e[1]): e[2] for e in nk[0]["from"]}
check("a capable qWDTT wire path is a source — its address from the node's read-back, the grant's date",
      els.get(("wdtt1", "10.66.66.2/32")) == NOW + DAY, nk)
check("…its RAW path is not (qWDTT 1.4.3 raw is not in the table)", ("wdttraw1", "10.70.66.2/32") not in els, nk)
check("csqtt 2.1.9 (no source check) is not; ildarmaga (not in the table) is not, on either path",
      not any(a in ("10.66.68.4/32", "10.66.67.3/32", "10.70.67.3/32") for _i, a in els), nk)
check("a device that never connected, and an ungranted user's device, are not", not any(a == "10.66.66.9/32" for _i, a in els) and
      all(i != "wdtt1" or a == "10.66.66.2/32" for i, a in els), nk)
check("no snapshot ⇒ no keyless source at all (fail closed)",
      not any(i == "wdtt1" for i, _a, _u in P.net_share_for_node(RK, "n1", P.node_networks(RK, "n1", SK)["carry"])[0]["from"]))
for name, snap_ in (("deactivated password", sk(passwords={"x": {"ip": "10.66.66.2", "is_deactivated": True}})),
                    ("stopped server", sk(stopped=True)), ("server not active", sk(active="failed")),
                    ("unknown build", sk(version="")), ("a DIFFERENT build of the fork", sk(version="1.4.1"))):
    n_ = P.net_share_for_node(RK, "n1", P.node_networks(RK, "n1", snap_)["carry"], snap_)
    check("%s ⇒ not a source" % name, not any(i == "wdtt1" for i, _a, _u in n_[0]["from"]), n_)
ik = P._keyless_index(dict(SNAP, wdtt=[{"iface": "wdtt2", "fork": "ildarmaga", "version": "1.5.40-2", "active": "active",
                                         "raw_iface": "wdttraw2", "passwords": {"ipw": {"ip": "", "raw_ip": "10.70.67.3"}}}]))
_orig_tbl = dict(P.KEYLESS_SHARE_BUILDS)
P.KEYLESS_SHARE_BUILDS["ildarmaga"] = {"wg": ("1.5.40-2",), "raw": ("1.5.40-2",)}
check("ildarmaga RAW is excluded even if a table entry tried to list it",
      P.keyless_sources(RK["peers"]["anna-ild"], RK["peers"]["anna-ild"]["targets"][0], ik) == ([], "raw_excluded"))
P.KEYLESS_SHARE_BUILDS.clear(); P.KEYLESS_SHARE_BUILDS.update(_orig_tbl)
rk = P.network_report(RK, "office", {"n1": SK})
gk = {g["user_id"]: g for g in next(e for e in rk["targets"] if e["node"] == "n1")["share"]["grants"]}
check("the report counts the vouched keyless device as reaching, and names why the others do not",
      gk["boris"]["devices"] == 3 and gk["boris"]["keyless_why"] == {"unenforced": 1}
      and gk["anna"]["devices"] == 1 and gk["anna"]["keyless_why"] == {"not_connected": 1, "unenforced": 1}, gk)
ubk = P.user_networks(RK, "boris", {"n1": SK})
_nets = lambda pid: [n["prefix"] for pr in ubk["peers"] if pr["peer_id"] == pid for t in pr["targets"] for n in t["networks"]]
check("\"Networks this user can reach\": the vouched keyless device reaches the office, the csqtt one does not",
      "192.168.1.0/24" in _nets("boris-wdtt") and "192.168.1.0/24" not in _nets("boris-csq"), ubk)

print("\n[15] the capability table promises only published builds")
for fork, paths in P.KEYLESS_SHARE_BUILDS.items():
    published = {v for v, _t in (P.CSQTT_BUILDS if fork == "csqtt" else (P.WDTT_BUILDS.get(fork) or []))}
    for path, vers in paths.items():
        check("%s %s: a known path, every version published %s" % (fork, path, list(vers)),
              path in ("wg", "raw") and vers and all(v in published for v in vers), published)
    # ⚠️ AND THE NEWEST ONE. 9e8cecf published wdttplus 18 and left the table at 15, so the moment a node installed the new
    # build every WDTT-Plus device on it was unvouched — Nobody at "Same user and their groups", never a share source — with
    # nothing anywhere failing. A new build of a vouched fork is vouched (rig run on the published asset) in the change that
    # publishes it, or this goes red and says so.
    newest = (P.CSQTT_BUILDS if fork == "csqtt" else (P.WDTT_BUILDS.get(fork) or [("", "")]))[0][0]
    check("%s: the newest published build (%s) is vouched on every path the fork is" % (fork, newest),
          all(newest in vers for vers in paths.values()), paths)
check("ildarmaga RAW is never in the table", "raw" not in (P.KEYLESS_SHARE_BUILDS.get("ildarmaga") or {}))

print("\n[16] §16 — the shared table")
fresh(); KS = Kernel(); N.run = KS
_sp = N._share_plan
N._share_plan = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
r, _raised, out = res(), False, None
try:
    out = N.reconcile_net_share(CFG, DESIRED, SHARE, r, now=NOW)
except Exception:
    _raised = True
N._share_plan = _sp
st = N._SHARE["status"] or {}
check("A2: a fault inside the reconciler does not stop the pass — every provider the reply names is carried for nobody, and it says so",
      not _raised and out is not None and next(x for x in out["awg0"] if x["public_key"] == K("O"))["allowed_ips"] == "10.8.0.2/32"
      and out["wg1"] == DESIRED["wg1"] and st.get("ok") is False and st.get("why") == "exception" and "boom" in st.get("detail", "")
      and bool(r["errors"]) and r["errors"][0].startswith("sharing:"), (_raised, st, r))
out = N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
check("A2: …and the next pass restricts again", out is DESIRED and (N._SHARE["status"] or {}).get("ok") is True and SH in KS.m.tables, N._SHARE["status"])
fresh(); KS = Kernel(); N.run = KS
N._share_plan = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
r, _raised, out = res(), False, None
try:
    out = N.reconcile_net_share(CFG, DESIRED, SHARE + [{"peer": ["x"], "from": 5}, "junk"], r, now=NOW)
except Exception:
    _raised = True
N._share_plan = _sp
check("A2: …and a malformed entry in the reply cannot break that fallback", not _raised and out is not None
      and next(x for x in out["awg0"] if x["public_key"] == K("O"))["allowed_ips"] == "10.8.0.2/32", (_raised, r))
_nm = N._net_members
N._net_members = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
fresh(); _raised = False
try:
    N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
except Exception:
    _raised = True
N._net_members = _nm
check("A2: …only when that fallback fails too does the pass abort, as before — never an unstripped ACL", _raised)

SN = [{"peer": K("O"), "from": [["wg1", "10.20.0.0/16", NOW + 3600], ["wg1", "10.20.7.0/24", 0], ["wg1", "10.20.7.128/25", NOW + 60],
                                ["wg1", "10.20.9.0/24", NOW + 7200], ["wg1", "10.9.0.4/32", 0]]}]
fresh(); KS = Kernel(); N.run = KS
N.reconcile_net_share(CFG, DESIRED, SN, res(), now=NOW)
check("nested grantee networks on one interface load — split, never refused (a prefix inside another refuses the whole load, measured)",
      (N._SHARE["status"] or {}).get("ok") is True and not KS.last_refused
      and spk("wg1", "10.20.7.9", "192.168.1.5") == "accept" and spk("wg1", "10.20.200.9", "192.168.1.5") == "accept", (N._SHARE["status"], KS.calls[-1:]))
check("⚠️ every date stays exact IN THE KERNEL with no reload — the panel may be unreachable (S5): the wider grant lapses on its own, "
      "the open-ended narrower one holds, a longer nested one outlives the wider",
      spk("wg1", "10.20.200.9", "192.168.1.5", at=3600) == "drop" and spk("wg1", "10.20.7.9", "192.168.1.5", at=10 ** 8) == "accept"
      and spk("wg1", "10.20.7.200", "192.168.1.5", at=10 ** 8) == "accept" and spk("wg1", "10.20.9.9", "192.168.1.5", at=3601) == "accept"
      and spk("wg1", "10.20.9.9", "192.168.1.5", at=7200) == "drop")
fresh(); KS = Kernel(nft102=True); N.run = KS
N.reconcile_net_share(CFG, DESIRED, SHARE, res(), now=NOW)
D23 = json.loads(json.dumps(DESIRED)); D23["awg0"][0]["allowed_ips"] = "10.8.0.2/32,192.168.0.0/23"
r = res()
out = N.reconcile_net_share(CFG, D23, SHARE, r, now=NOW)
check("a swap nft 1.0.2 refuses (a restricted network grown in place, /24 → /23) is DECLARED in the same pass — every network stays "
      "carried, none stripped", out is D23 and (N._SHARE["status"] or {}).get("ok") is True and len(KS.loads) == 2
      and KS.loads[-1].startswith(DECLARE) and not r["errors"] and spk("awg0", "10.8.0.6", "192.168.0.5") == "drop"
      and spk("awg0", "10.8.0.3", "192.168.1.5") == "accept", (N._SHARE["status"], r, len(KS.loads)))
_mm = Kernel()
try:
    _mm.m.load("table inet t {\n  chain p0 { counter drop; }\n"
               "  map m { type ipv4_addr : verdict; flags interval; elements = { 192.168.0.0/16 : jump p0, 192.168.1.0/24 : jump p0 } }\n}\n")
    _mref = False
except Exception:
    _mref = True
check("the model refuses overlapping map keys, as nft does (measured on 1.0.9 and 1.0.2)", _mref)

print("\n%s" % ("ALL PASS" if not FAILS else "%d FAIL" % len(FAILS)))
sys.exit(1 if FAILS else 0)
