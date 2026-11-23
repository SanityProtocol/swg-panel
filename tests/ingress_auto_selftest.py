#!/usr/bin/env python3
"""Self-test for an ingress address "Auto (public IP)" that stays Auto and follows the box (1.8.12 item 21;
docs/RELEASE-1.8.12-PLAN.md §21.1).

Picking Auto stores a flag (`endpoint_host_auto`) and keeps `endpoint_host` holding a real address, so every reader is
unchanged. The sync moves that address to the node's public IP only AWAY from an address that is gone from the box, after
INGRESS_FOLLOW_SYNCS reports in a row, with the interfaces' own copies of the old address and one event.

Panel (the real /api/nodes/update door and the real _node_sync_apply, on a temp store; no network):
  [1] Auto picked → the flag, the address resolved from the last snapshot; kept across syncs (no flip back)
  [2] already Auto + a Settings save of anything ("" again) → nothing moves, even when the box's first address changed
  [3] the address gone → moves only after 6 syncs in a row, once, with the interfaces' copies and one event;
      a gap of 5 then a return moves nothing; a still-present address never moves
  [4] no public address reported (NAT, or the node said nothing) → nothing moves, never to ""; a carrier-NAT /
      Tailscale address (100.64.0.0/10) is never taken — not at the pick, not on a follow (review F2/F4)
  [5] an IP or a hostname picked → the flag cleared, nothing follows
  [6] a node never on Auto: "" on an empty record stays "" with no flag (today's fill-once)
  [7] /api/nodes publishes the flag only when set
  [8] the stale-IP Issues line: unchanged — it fires for a pinned gone address
SPA (source, as shipped):
  [9] the Settings draft reads "" for an Auto node, and its save sends the address only when the draft changed it (a
      draft taken before the first sync must not pick Auto — review F3); the node gear sheet sends no `endpoint_host`
Optional:
  [B] SWG_INGRESS_BASE=<commit>: a node never on Auto — the store, the events and the sync reply after a run of syncs and
      a Settings save are byte-identical to that commit's panel.

Run: python3 tests/ingress_auto_selftest.py   (0 = pass)
     --perturb-flag · --perturb-resolve · --perturb-already · --perturb-count · --perturb-gone · --perturb-empty ·
     --perturb-pin · --perturb-ifaces · --perturb-event · --perturb-publish · --perturb-cgnat · --perturb-unchanged ·
     --perturb-draft · --perturb-sheet —
     each plants one regression (PLANTS below), RED.
"""
import copy, importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
SETTINGS_JS = os.path.join(ROOT, "js", "screen-settings.js")
SHEETS_JS = os.path.join(ROOT, "js", "sheets-crud.js")
for _v in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_v, None)

# (file, anchor, replacement) — each must match exactly once, or the run would FALSE-PASS
PLANTS = {
    "--perturb-flag": ("P", '                _nd["endpoint_host_auto"] = True\n', "                pass\n"),
    "--perturb-resolve": ("P", '                _nd["endpoint_host"] = (_ingress_ip((deps.get("node_snaps") or {}).get(nid))\n'
                               '                                        or (_nd.get("endpoint_host") or "").strip())',
                          '                _nd["endpoint_host"] = (_nd.get("endpoint_host") or "").strip()'),
    "--perturb-already": ("P", '            elif _nd.get("endpoint_host_auto"):\n                pass',
                          '            elif False:\n                pass'),
    "--perturb-count": ("P", "INGRESS_FOLLOW_SYNCS = 6 ", "INGRESS_FOLLOW_SYNCS = 1 "),
    "--perturb-gone": ("P", ' and old not in (snap.get("node_ips") or [])):', "):"),
    "--perturb-empty": ("P", "    if not (old and pub and old != pub", "    if not (old and old != pub"),
    "--perturb-pin": ("P", '                _nd.pop("endpoint_host_auto", None)\n', ""),
    "--perturb-ifaces": ("P", '            ov["endpoint_host"] = pub\n', "            pass\n"),
    "--perturb-event": ("P", '                ev_append(Handler.deps["roster_path"], "node", nid, "Ingress address followed the public IP",',
                        '                (lambda *a, **k: None)(Handler.deps["roster_path"], "node", nid, "Ingress address followed the public IP",'),
    "--perturb-publish": ("P", '**({"endpoint_host_auto": True} if c.get("endpoint_host_auto") else {}),', ""),
    "--perturb-cgnat": ("P", "        if a.version == 4 and a.is_global:",
                        "        if a.version == 4 and not (a.is_private or a.is_loopback or a.is_link_local):"),
    "--perturb-unchanged": ("S", 'const ehSend = eq(e.endpoint_host, o.endpoint_host) ? undefined : (e.endpoint_host || "").trim();',
                            'const ehSend = (e.endpoint_host || "").trim();'),
    "--perturb-draft": ("S", 'endpoint_host: n.endpoint_host_auto ? "" : (n.endpoint_host || ""),', 'endpoint_host: n.endpoint_host || "",'),
    "--perturb-sheet": ("C", "name: name.trim(), color, mesh_port: ovPort,", "name: name.trim(), color, endpoint_host: node.endpoint_host, mesh_port: ovPort,"),
}
PLANT = next((a for a in sys.argv[1:] if a in PLANTS), None)

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:600]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def _src(path, which):
    s = open(path, encoding="utf-8").read()
    if PLANT and PLANTS[PLANT][0] == which:
        _, a, b = PLANTS[PLANT]
        assert s.count(a) == 1, "perturbation anchor (%s) missing or not unique — this run would FALSE-PASS" % PLANT
        s = s.replace(a, b, 1)
    return s


def _load(src, name):
    p = os.path.join(tempfile.mkdtemp(prefix="ing-"), name + ".py")
    open(p, "w", encoding="utf-8").write(src)
    l = importlib.machinery.SourceFileLoader(name, p)
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, l))
    try:
        l.exec_module(mod)
    except SystemExit:
        pass
    return mod


P = _load(_src(PANEL, "P"), "swgpanel_ing")
TMP = tempfile.mkdtemp(prefix="ing-fx-")
X = "n1"
A1, A2, A3, B1 = "45.10.20.1", "45.10.20.2", "45.10.20.3", "77.30.40.9"     # public-looking (TEST-NETs count as private)


def fixture(tag, **rec):
    d = os.path.join(TMP, tag); os.makedirs(os.path.join(d, "stats"), exist_ok=True)
    nodes = {X: dict({"id": X, "name": "forge", "token_hash": "x", "token_sha": "x", "stats_file": "stats-%s.json" % X,
                      "ifaces": {"awg0": {"endpoint_host": A1}, "wg1": {"endpoint_host": "vpn.example.com"}, "wg2": {}}},
                     **rec)}
    np_ = os.path.join(d, "nodes.json"); rp = os.path.join(d, "users.json")
    json.dump(nodes, open(np_, "w")); json.dump({"version": 1, "users": {}, "peers": {}}, open(rp, "w"))
    deps = {"fleet": {"nodes_path": np_, "roster_path": rp, "stats_dir": os.path.join(d, "stats")},
            "roster_path": rp, "nodes_path": np_, "stats_dir": os.path.join(d, "stats"),
            "panel_settings_path": os.path.join(d, "panel-settings.json"), "panel_settings": {},
            "node_snaps": {X: {"node_ips": [A1, A2, "10.0.0.5"], "interfaces": {}}},
            "node_seen": {}, "live_samples": {}, "now": lambda: int(time.time())}
    return deps


def mod_for(deps, mod=None):
    mod = mod or P
    mod.Handler.deps = deps
    getattr(mod, "_INGRESS_SEEN", {}).clear()
    return mod


class _Sync:
    headers = {}


def sync(deps, node_ips, mod=None):
    mod = mod or P
    snap = {"node_ips": list(node_ips), "interfaces": {}}
    deps["node_snaps"][X] = snap
    nodes = json.load(open(deps["nodes_path"]))
    return mod.Handler._node_sync_apply(_Sync(), X, nodes[X], nodes, snap, None)


def rec(deps):
    return json.load(open(deps["nodes_path"]))[X]


def events(deps):
    p = os.path.join(os.path.dirname(deps["roster_path"]), "events.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def follows(deps):
    return [e for e in events(deps) if e.get("verb") == "Ingress address followed the public IP"]


def save(deps, eh, mod=None):
    return (mod or P).api("POST", "/api/nodes/update", {}, {"id": X, "endpoint_host": eh}, deps)


N = P.INGRESS_FOLLOW_SYNCS if not PLANT == "--perturb-count" else 6

print("[1] Auto picked: the flag, the address resolved, kept across syncs")
deps = fixture("t1", endpoint_host="vpn.example.com")
mod_for(deps)
st, r = save(deps, "")
r1 = rec(deps)
check("the save is 200", st == 200, (st, r))
check("the flag is stored", r1.get("endpoint_host_auto") is True, r1)
check("the address is the snapshot's first public IP, never blank", r1.get("endpoint_host") == A1, r1.get("endpoint_host"))
for _ in range(N + 3):
    sync(deps, [A1, A2, "10.0.0.5"])
r1 = rec(deps)
check("after %d syncs still Auto, on the same address" % (N + 3), r1.get("endpoint_host_auto") is True and r1.get("endpoint_host") == A1, r1)
check("no event for a node that did not move", not follows(deps), follows(deps))

print("[2] already Auto: a Settings save of anything posts \"\" again — nothing moves")
for _ in range(2):
    sync(deps, [A3, A1, A2])                 # a new address sorts first; the stored one is still on the box
check("the stored address is still on the box: the sync leaves it", rec(deps).get("endpoint_host") == A1, rec(deps))
save(deps, "")
check("a second \"\" keeps the address (no re-resolve to the new first address)", rec(deps).get("endpoint_host") == A1
      and rec(deps).get("endpoint_host_auto") is True, rec(deps))
for _ in range(N + 2):
    sync(deps, [A3, A1, A2])
check("an address still on the box never moves", rec(deps).get("endpoint_host") == A1 and not follows(deps), (rec(deps), follows(deps)))

print("[3] the address gone: moves after %d syncs in a row, once, with the interfaces' copies and one event" % N)
deps = fixture("t3", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
for _ in range(N - 1):
    sync(deps, [B1, "10.0.0.5"])
check("%d syncs: not yet" % (N - 1), rec(deps).get("endpoint_host") == A1, rec(deps).get("endpoint_host"))
sync(deps, [A1, "10.0.0.5"])                 # the old address back for one sync: the count starts again
for _ in range(N - 1):
    sync(deps, [B1, "10.0.0.5"])
check("a run broken by one report of the old address moves nothing", rec(deps).get("endpoint_host") == A1, rec(deps).get("endpoint_host"))
sync(deps, [B1, "10.0.0.5"])
r3 = rec(deps)
check("%d in a row: moved to the new public IP" % N, r3.get("endpoint_host") == B1 and r3.get("endpoint_host_auto") is True, r3)
check("the interface that copied the old address moves with it; a hostname and an empty one do not",
      r3["ifaces"]["awg0"].get("endpoint_host") == B1 and r3["ifaces"]["wg1"].get("endpoint_host") == "vpn.example.com"
      and "endpoint_host" not in r3["ifaces"]["wg2"], r3["ifaces"])
ev = follows(deps)
check("one event, naming both addresses",
      len(ev) == 1 and ev[0].get("verb") == "Ingress address followed the public IP" and A1 in str(ev[0].get("detail"))
      and B1 in str(ev[0].get("detail")), ev)
for _ in range(N + 2):
    sync(deps, [B1, "10.0.0.5"])
check("settled: no second move, no second event", rec(deps).get("endpoint_host") == B1 and len(follows(deps)) == 1, follows(deps))
deps = fixture("t3b", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
for i in range(N + 2):
    sync(deps, [B1 if i % 2 else A2, "10.0.0.5"])   # the gone address, and a new first one that keeps changing
check("a new address that does not hold for %d syncs moves nothing" % N, rec(deps).get("endpoint_host") == A1, rec(deps).get("endpoint_host"))

print("[4] no public address reported → nothing moves, never to \"\"")
deps = fixture("t4", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
for _ in range(N + 2):
    sync(deps, ["10.0.0.5", "192.168.1.4"])
check("behind NAT: the address stays", rec(deps).get("endpoint_host") == A1 and not follows(deps), rec(deps))
for _ in range(N + 2):
    sync(deps, [])
check("the node said nothing: the address stays", rec(deps).get("endpoint_host") == A1, rec(deps))
CG = "100.101.2.3"
for _ in range(N + 2):
    sync(deps, [CG, "10.0.0.5"])            # the public NIC renumbering; a Tailscale address is all that is left
check("a carrier-NAT / Tailscale address is not followed", rec(deps).get("endpoint_host") == A1 and not follows(deps), rec(deps))
for _ in range(N):
    sync(deps, [CG, B1, "10.0.0.5"])
check("the new public address is, past the 100.64/10 one listed first", rec(deps).get("endpoint_host") == B1, rec(deps))
deps = fixture("t4c", endpoint_host="vpn.example.com")
mod_for(deps)
deps["node_snaps"][X] = {"node_ips": [CG, A2], "interfaces": {}}
save(deps, "")
check("picking Auto resolves past a 100.64/10 address", rec(deps).get("endpoint_host") == A2, rec(deps))

print("[5] an IP or a hostname picked → the flag cleared, nothing follows")
for pick in (A2, "node.example.com"):
    deps = fixture("t5" + pick, endpoint_host=A1, endpoint_host_auto=True)
    mod_for(deps)
    save(deps, pick)
    r5 = rec(deps)
    check("%s pinned, the flag gone" % pick, r5.get("endpoint_host") == pick and "endpoint_host_auto" not in r5, r5)
    for _ in range(N + 2):
        sync(deps, [B1])
    check("%s: the box moved, the pin stays" % pick, rec(deps).get("endpoint_host") == pick and not follows(deps), rec(deps))

print("[6] a node never on Auto")
deps = fixture("t6")
mod_for(deps)
save(deps, "")
check("\"\" on an empty record stays \"\" with no flag", rec(deps).get("endpoint_host") == "" and "endpoint_host_auto" not in rec(deps), rec(deps))
sync(deps, [A1])
check("the first sync fills it once, as before", rec(deps).get("endpoint_host") == A1 and "endpoint_host_auto" not in rec(deps), rec(deps))
for _ in range(N + 2):
    sync(deps, [B1])
check("then it is an ordinary stored address: it does not follow", rec(deps).get("endpoint_host") == A1 and not follows(deps), rec(deps))

print("[7] /api/nodes publishes the flag only when set")
def _pub_row(deps):
    st, r = P.api("GET", "/api/nodes", {}, {}, deps)
    rows = (r.get("data") or {}).get("nodes") if isinstance(r.get("data"), dict) else r.get("data")
    return st, next((x for x in rows or [] if x.get("id") == X), None)
deps = fixture("t7", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
st, row = _pub_row(deps)
check("Auto: the row carries endpoint_host_auto and the address", st == 200 and row and row.get("endpoint_host_auto") is True
      and row.get("endpoint_host") == A1, (st, row and {k: row.get(k) for k in ("endpoint_host", "endpoint_host_auto")}))
deps = fixture("t7b", endpoint_host=A1)
mod_for(deps)
st, row = _pub_row(deps)
check("not Auto: no key at all", st == 200 and row and "endpoint_host_auto" not in row, row and sorted(row)[:5])

print("[8] the stale-IP Issues line is unchanged")
_iss = P._node_issues({"endpoint_host": A1}, {"node_ips": [B1]})
check("a pinned gone address still says so", any("no longer on this node" in str(i) for i in _iss), _iss)

print("[9] SPA, as shipped")
sjs = _src(SETTINGS_JS, "S")
check("the Settings draft reads \"\" for an Auto node (the picker shows Auto; a move is never an edit)",
      'endpoint_host: n.endpoint_host_auto ? "" : (n.endpoint_host || ""),' in sjs)
check("the Settings save sends the address only when the draft changed it (a pre-sync \"\" must not pick Auto)",
      'const ehSend = eq(e.endpoint_host, o.endpoint_host) ? undefined : (e.endpoint_host || "").trim();' in sjs
      and "ip_learning: e.ip_learning !== false, endpoint_host: ehSend," in sjs)
cjs = _src(SHEETS_JS, "C")
a = cjs.find("export function NodeEditSheet(")
body = cjs[a:cjs.find("\n}\n", a)] if a >= 0 else ""
call = body[body.find("api.nodeUpdate("):body.find("})", body.find("api.nodeUpdate("))] if "api.nodeUpdate(" in body else ""
check("the node gear sheet's save sends no endpoint_host (it would clear Auto on a rename)", call and "endpoint_host" not in call, call[:200])

# ── optional: the byte-identical claim for a node never on Auto ────────────────────────────────────────────────────────
BASE = os.environ.get("SWG_INGRESS_BASE")
if BASE and not PLANT:
    print("[B] a node never on Auto vs %s" % BASE)
    PB = _load(subprocess.run(["git", "-C", ROOT, "show", "%s:swg-panel-server" % BASE], capture_output=True, text=True,
                              check=True).stdout, "swgpanel_ing_base")
    def run(mod, tag, start, picks):
        deps = fixture(tag, **start)
        mod_for(deps, mod)
        out = [save(deps, picks[-1], mod)] if -1 in picks else []        # -1: a save before the first sync
        for i, ips in enumerate([[A1, A2], [A1, A2], [B1], [B1], [B1], [B1], [B1], [B1], [B1], ["10.0.0.5"], []]):
            out.append(sync(deps, ips, mod))
            if i in picks:
                out.append(save(deps, picks[i], mod))
        evs = [{k: v for k, v in e.items() if k not in ("eid", "ts")} for e in events(deps)]
        return out, rec(deps), evs
    # "" posted on a record that holds an address IS picking Auto, so "" is posted only where nothing is stored yet
    for ci, (start, picks) in enumerate((({}, {}), ({}, {-1: ""}), ({"endpoint_host": ""}, {-1: ""}),
                                         ({"endpoint_host": A1}, {}), ({"endpoint_host": "vpn.example.com"}, {3: "x.example.com"}),
                                         ({"endpoint_host": A1}, {2: A2}))):
        a_, b_ = run(P, "bn%d" % ci, start, picks), run(PB, "bb%d" % ci, start, picks)
        check("start %s, saves %s: every sync reply, the store and the events alike" % (start, picks), a_ == b_,
              next(([x, y] for x, y in zip(a_[0], b_[0]) if x != y), None) or [a_[1:], b_[1:]])

print("\n%s" % ("FAIL: %d check(s) red%s" % (len(FAILS), (" (" + PLANT + ")") if PLANT else "") if FAILS
                else "OK — the Auto ingress holds" + ((" (" + PLANT + " NOT caught)") if PLANT else "")))
sys.exit(1 if FAILS else 0)
