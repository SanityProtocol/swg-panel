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
  [3s] the servers' own copies (§21.2): a WDTT/csqtt `listen` (and "Listen on" pin) on the old address moves, port kept; a
       hostname or a wildcard does not (its pin still does); each vk-turn-proxy on it, or pinned to it, gets one `manage`
       request — not a stopped one, not one installing, not one with a request in flight, nothing on a node that cannot
       manage proxies; the move's event names every server moved (each restarts once)
  [3p] a proxy busy at the move follows later (§21.3): the old address is kept (`endpoint_host_prev`); a proxy stopped
       then started is moved on the next sync, with its own event; a pending install's address is rewritten at the move;
       a proxy asked once is not asked again inside FO_TP_RETRY, and after INGRESS_TP_TRIES asks it is given up with one
       event; the kept addresses are a list (a proxy stopped across two moves still follows); every move and every pin
       forgets the node's asks, so a later move asks at once — moving BACK to an address given up on included;
       nothing while the old address is back on the box or the node reports no addresses; a pin clears the flag and the
       kept addresses; the fingerprint leaves the kept addresses out (review F4)
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
     --perturb-servers · --perturb-proxies · --perturb-stopped · --perturb-inflight · --perturb-installing ·
     --perturb-pinonly · --perturb-evnames · --perturb-later · --perturb-retry · --perturb-prevback · --perturb-nonips ·
     --perturb-pending · --perturb-prevpin · --perturb-laterev · --perturb-prevlist · --perturb-cap · --perturb-forget · --perturb-pinforget ·
     --perturb-fpx · --perturb-quitev · --perturb-evaddr · --perturb-draft · --perturb-sheet —
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
    "--perturb-servers": ("P", '                inst["listen"] = "%s:%s" % (pub, p)\n', "                pass\n"),
    "--perturb-proxies": ("P", '        node.setdefault("turn", {})[svc] = rq\n', "        pass\n"),
    "--perturb-stopped": ("P", " or tp.get(\"stopped\") or ", " or "),
    "--perturb-inflight": ("P", " or not _TURN_SVC_RE.match(svc) \\\n                or svc in (node.get(\"turn\") or {}):",
                           " or not _TURN_SVC_RE.match(svc):"),
    "--perturb-installing": ("P", " or tp.get(\"installing\") or ", " or "),
    "--perturb-pinonly": ("P", "        if not (mv_l or mv_pin) or tp.get(", "        if not mv_l or tp.get("),
    "--perturb-evnames": ("P", ' + (" (%s)" % ", ".join(_all) if _all else ""))', ")"),
    "--perturb-later": ("P", '        _tq, _tquit = _ingress_proxies(nid, node, snap) if node.get("endpoint_host_prev") else ([], [])',
                        "        _tq, _tquit = [], []"),
    "--perturb-retry": ("P", "        if now_ - at < FO_TP_RETRY:\n            continue\n", ""),
    "--perturb-prevback": ("P", "if a not in nips and a != new]", "if a != new]"),
    "--perturb-nonips": ("P", 'node.get("endpoint_host_auto") and nips) or not', 'node.get("endpoint_host_auto")) or not'),
    "--perturb-prevlist": ("P", ' + [a for a in _ingress_prev(node) if a not in (old, pub)][:INGRESS_PREV_KEEP - 1]', ""),
    "--perturb-cap": ("P", "        if n >= INGRESS_TP_TRIES:", "        if False:"),
    "--perturb-forget": ("P", "[:INGRESS_PREV_KEEP - 1]\n    _ingress_forget(nid)\n", "[:INGRESS_PREV_KEEP - 1]\n"),
    "--perturb-pinforget": ("P", "# …and what Auto moved away from (§21.3)\n                    _ingress_forget(nid)",
                            "# …and what Auto moved away from (§21.3)\n                    pass"),
    "--perturb-fpx": ("P", '    ("endpoint_host_prev",      "Auto', '    ("endpoint_host_prev_x",    "Auto'),
    "--perturb-quitev": ("P", '                    ev_append(Handler.deps["roster_path"], "node", nid, "Could not move turn-proxy to the ingress address",',
                         '                    (lambda *a, **k: None)(Handler.deps["roster_path"], "node", nid, "Could not move turn-proxy to the ingress address",'),
    "--perturb-evaddr": ("P", '"→ %s (%s)" % (node.get("endpoint_host"), ", ".join(_tq)))', '", ".join(_tq))'),
    "--perturb-pending": ("P", '                req["listen"] = "%s:%s" % (pub, p)\n', "                pass\n"),
    "--perturb-prevpin": ("P", '                if _nd.pop("endpoint_host_prev", None) is not None:', '                if _nd.get("endpoint_host_prev") is None:'),
    "--perturb-laterev": ("P", '                    ev_append(Handler.deps["roster_path"], "node", nid, "Moving turn-proxy to the ingress address",',
                          '                    (lambda *a, **k: None)(Handler.deps["roster_path"], "node", nid, "Moving turn-proxy to the ingress address",'),
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
    getattr(mod, "_INGRESS_TP_TRIED", {}).clear()
    return mod


class _Sync:
    headers = {}


def sync(deps, node_ips, mod=None, **extra):
    mod = mod or P
    snap = dict({"node_ips": list(node_ips), "interfaces": {}}, **extra)
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

print("[3s] the servers' own copies of the address")
_srv = {"wdtt": {"wdtt1": {"iface": "wdtt1", "listen": A1 + ":56000", "bind_ip": A1},
                 "wdtt2": {"iface": "wdtt2", "listen": "0.0.0.0:56004"}},
        "csqtt": {"csqtt1": {"iface": "csqtt1", "listen": "vpn.example.com:56020"},
                  "csqtt2": {"iface": "csqtt2", "listen": A1 + ":56002"},
                  "csqtt3": {"iface": "csqtt3", "listen": "vpn.example.com:56030", "bind_ip": A1}},
        # a request in flight: a `delete` stays until the node stops reporting the proxy — no clock in it (review F8)
        "turn": {"vk-turn-proxy-anton48-56013": {"action": "delete", "at": int(time.time())}}}
TP = [{"service": "vk-turn-proxy-anton48-56010", "listen": A1 + ":56010", "bind_ip": A1},
      {"service": "vk-turn-proxy-anton48-56011", "listen": A1 + ":56011", "stopped": True},
      {"service": "vk-turn-proxy-anton48-56012", "listen": "0.0.0.0:56012"},
      {"service": "vk-turn-proxy-anton48-56013", "listen": A1 + ":56013"},
      {"service": "vk-turn-proxy-samosvalishe-56014", "listen": "vpn.example.com:56014"},
      {"service": "vk-turn-proxy-samosvalishe-56015", "listen": "vpn.example.com:56015", "bind_ip": A1},
      {"service": "vk-turn-proxy-anton48-56016", "listen": A1 + ":56016", "installing": True}]
deps = fixture("t3s", endpoint_host=A1, endpoint_host_auto=True, **copy.deepcopy(_srv))
mod_for(deps)
for _ in range(N - 1):
    sync(deps, [B1], turn_proxies=TP)
check("before the move: no server touched, no request", rec(deps).get("wdtt") == _srv["wdtt"] and rec(deps).get("turn") == _srv["turn"], rec(deps))
sync(deps, [B1], turn_proxies=TP)
r = rec(deps)
check("WDTT on the old address: listen and its Listen-on pin moved, port kept",
      r["wdtt"]["wdtt1"].get("listen") == B1 + ":56000" and r["wdtt"]["wdtt1"].get("bind_ip") == B1, r["wdtt"]["wdtt1"])
check("csqtt on the old address moved; a hostname and a wildcard did not",
      r["csqtt"]["csqtt2"].get("listen") == B1 + ":56002" and r["csqtt"]["csqtt1"].get("listen") == "vpn.example.com:56020"
      and r["wdtt"]["wdtt2"].get("listen") == "0.0.0.0:56004", (r["csqtt"], r["wdtt"]["wdtt2"]))
check("a hostname listen pinned to the old address: the pin moves, the listen stays",
      r["csqtt"]["csqtt3"] == {"iface": "csqtt3", "listen": "vpn.example.com:56030", "bind_ip": B1}, r["csqtt"]["csqtt3"])
_t = r.get("turn") or {}
_q = _t.get("vk-turn-proxy-anton48-56010") or {}
check("the proxy on the old address gets one `manage` with the new address and its pin",
      _q.get("action") == "manage" and _q.get("listen") == B1 + ":56010" and _q.get("bind_ip") == B1
      and set(_q) == {"action", "listen", "bind_ip", "at"}, _q)
check("a proxy on a hostname pinned to the old address gets the pin alone",
      (_t.get("vk-turn-proxy-samosvalishe-56015") or {}).get("bind_ip") == B1
      and set(_t.get("vk-turn-proxy-samosvalishe-56015") or {}) == {"action", "bind_ip", "at"}, _t.get("vk-turn-proxy-samosvalishe-56015"))
check("no request for a stopped proxy, an installing one, a wildcard one or an unpinned hostname one",
      not {"vk-turn-proxy-anton48-56011", "vk-turn-proxy-anton48-56012", "vk-turn-proxy-samosvalishe-56014",
           "vk-turn-proxy-anton48-56016"} & set(_t), sorted(_t))
_ev = (follows(deps) or [{}])[-1].get("detail", "")
check("the move's event names every server it moved, and none it did not",
      all(x in _ev for x in ("wdtt1", "csqtt2", "csqtt3", "vk-turn-proxy-anton48-56010", "vk-turn-proxy-samosvalishe-56015"))
      and not any(x in _ev for x in ("wdtt2", "csqtt1", "56011", "56012", "56013", "56014", "56016")), _ev)
check("a request already in flight is left as it is", _t.get("vk-turn-proxy-anton48-56013") == _srv["turn"]["vk-turn-proxy-anton48-56013"],
      _t.get("vk-turn-proxy-anton48-56013"))
for _ in range(N + 2):
    sync(deps, [B1], turn_proxies=TP)            # the node has not applied yet: it still reports the old listen
_t2 = rec(deps).get("turn") or {}
check("one-shot: no second request while the node applies (a request may only close, by the clear loop's rule)",
      set(_t2) <= set(_t) and all(_t2[k] == _t[k] for k in _t2) and len(follows(deps)) == 1, (_t2, follows(deps)))
check("the listen-carrying request stays until the node reports the new listen (no clock: its age is far below 60 s)",
      _t2.get("vk-turn-proxy-anton48-56010") == _q, _t2.get("vk-turn-proxy-anton48-56010"))
deps = fixture("t3t", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
for _ in range(N):
    sync(deps, [B1], turn_proxies=TP, turn_manage=False)
check("a node that cannot manage proxies gets no request", rec(deps).get("endpoint_host") == B1 and not rec(deps).get("turn"), rec(deps))

print("[3p] a proxy busy at the move follows later")
def edit(deps, fn):
    n = json.load(open(deps["nodes_path"])); fn(n[X]); json.dump(n, open(deps["nodes_path"], "w"))
def later(deps):
    return [e for e in events(deps) if e.get("verb") == "Moving turn-proxy to the ingress address"]
def gaveup(deps):
    return [e for e in events(deps) if e.get("verb") == "Could not move turn-proxy to the ingress address"]
S11, S20 = "vk-turn-proxy-anton48-56011", "vk-turn-proxy-anton48-56020"
deps = fixture("t3p", endpoint_host=A1, endpoint_host_auto=True,
               turn={S20: {"action": "install", "owner": "anton48", "listen": A1 + ":56020", "connect": "127.0.0.1:51820",
                           "at": int(time.time())}})
mod_for(deps)
TPs = [{"service": S11, "listen": A1 + ":56011", "stopped": True}]
for _ in range(N):
    sync(deps, [B1], turn_proxies=TPs)
r = rec(deps)
check("the move keeps the old address in endpoint_host_prev", r.get("endpoint_host") == B1 and r.get("endpoint_host_prev") == [A1], r)
check("a pending install carrying the old address is rewritten in place (no new request)",
      (r.get("turn") or {}).get(S20, {}).get("listen") == B1 + ":56020" and (r.get("turn") or {}).get(S20, {}).get("action") == "install",
      r.get("turn"))
check("the stopped proxy is not asked at the move", S11 not in (r.get("turn") or {}), r.get("turn"))
TPr = [{"service": S11, "listen": A1 + ":56011", "running": True}]
sync(deps, [B1], turn_proxies=TPr)                       # the operator starts it: it comes up on the old address
q = (rec(deps).get("turn") or {}).get(S11) or {}
check("started later: moved on the next sync", q.get("action") == "manage" and q.get("listen") == B1 + ":56011", q)
check("…with its own event naming it and where it goes", len(later(deps)) == 1 and S11 in later(deps)[0].get("detail", "")
      and B1 in later(deps)[0].get("detail", "") and len(follows(deps)) == 1, (later(deps), follows(deps)))
edit(deps, lambda n: (n.get("turn") or {}).pop(S11, None))                 # the request closed without the node applying it
for _ in range(3):
    sync(deps, [B1], turn_proxies=TPr)
check("not asked again inside the retry window", S11 not in (rec(deps).get("turn") or {}) and len(later(deps)) == 1,
      (rec(deps).get("turn"), later(deps)))
def age_tries(): # the retry window has passed for every ask (counts kept)
    for k, (at, n) in list(P._INGRESS_TP_TRIED.items()):
        P._INGRESS_TP_TRIED[k] = (at - P.FO_TP_RETRY - 1, n)
age_tries()                                              # …the window has passed
sync(deps, [B1], turn_proxies=TPr)
check("asked again after it", ((rec(deps).get("turn") or {}).get(S11) or {}).get("listen") == B1 + ":56011", rec(deps).get("turn"))
edit(deps, lambda n: (n.get("turn") or {}).pop(S11, None)); age_tries()
sync(deps, [B1], turn_proxies=TPr)
check("a third ask", ((rec(deps).get("turn") or {}).get(S11) or {}).get("listen") == B1 + ":56011" and len(later(deps)) == 3,
      (rec(deps).get("turn"), later(deps)))
edit(deps, lambda n: (n.get("turn") or {}).pop(S11, None)); age_tries()
for _ in range(3):
    sync(deps, [B1], turn_proxies=TPr)
    age_tries()
check("after %d asks: given up — no fourth, one event saying so" % P.INGRESS_TP_TRIES,
      S11 not in (rec(deps).get("turn") or {}) and len(later(deps)) == 3 and len(gaveup(deps)) == 1
      and S11 in gaveup(deps)[0].get("detail", ""), (rec(deps).get("turn"), later(deps), gaveup(deps)))
edit(deps, lambda n: (n.get("turn") or {}).pop(S11, None)); P._INGRESS_TP_TRIED.clear()
sync(deps, [A1, B1], turn_proxies=TPr)
check("the old address back on the box: nothing asked", S11 not in (rec(deps).get("turn") or {}), rec(deps).get("turn"))
P._INGRESS_TP_TRIED.clear()
sync(deps, [], turn_proxies=TPr)
check("the node reports no addresses: nothing asked", S11 not in (rec(deps).get("turn") or {}), rec(deps).get("turn"))
save(deps, B1)
check("a pin clears the flag and the kept address", "endpoint_host_auto" not in rec(deps) and "endpoint_host_prev" not in rec(deps),
      rec(deps))
P._INGRESS_TP_TRIED.clear()
sync(deps, [B1], turn_proxies=TPr)
check("…and nothing is asked after it", S11 not in (rec(deps).get("turn") or {}), rec(deps).get("turn"))
C1 = "77.30.40.10"
deps = fixture("t3q", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
TP2 = [{"service": S11, "listen": A1 + ":56011", "stopped": True},
       {"service": S10, "listen": A1 + ":56010", "running": True}] if (S10 := "vk-turn-proxy-anton48-56010") else []
for _ in range(N):
    sync(deps, [B1], turn_proxies=TP2)
check("first move: the running proxy is asked, the stopped one not", S10 in (rec(deps).get("turn") or {})
      and S11 not in (rec(deps).get("turn") or {}), rec(deps).get("turn"))
edit(deps, lambda n: (n.get("turn") or {}).pop(S10, None))   # …and the node never applied it
for _ in range(N):
    sync(deps, [C1], turn_proxies=TP2)                    # renumbered again, inside the retry window
r = rec(deps)
check("a second move keeps both addresses it left, newest first", r.get("endpoint_host") == C1
      and r.get("endpoint_host_prev") == [B1, A1], r.get("endpoint_host_prev"))
check("a later move asks at once, to the new address (a new move forgets the last one's asks)",
      ((r.get("turn") or {}).get(S10) or {}).get("listen") == C1 + ":56010", r.get("turn"))
sync(deps, [C1], turn_proxies=[{"service": S11, "listen": A1 + ":56011", "running": True}])
check("a proxy stopped across both moves follows when started", ((rec(deps).get("turn") or {}).get(S11) or {}).get("listen")
      == C1 + ":56011", rec(deps).get("turn"))
check("the fingerprint leaves the kept addresses out (Auto's bookkeeping, not configuration)",
      "endpoint_host_prev" in P._FP_EXCLUDE_PATS)
deps = fixture("t3r", endpoint_host=A1, endpoint_host_auto=True)
mod_for(deps)
TP3 = [{"service": S10, "listen": A1 + ":56010", "running": True}]
def fails(ips):                                           # the node takes the ask and never applies it
    edit(deps, lambda n: (n.get("turn") or {}).pop(S10, None)); age_tries(); sync(deps, ips, turn_proxies=TP3)
for _ in range(N):
    sync(deps, [B1], turn_proxies=TP3)
for _ in range(3):
    fails([B1])
check("asked three times to B, then given up", len(gaveup(deps)) == 1 and S10 not in (rec(deps).get("turn") or {}),
      (gaveup(deps), rec(deps).get("turn")))
check("the retry memory holds one entry per proxy of the node", [k for k in P._INGRESS_TP_TRIED if k[0] == X] == [(X, S10)],
      sorted(P._INGRESS_TP_TRIED))
for _ in range(N):
    sync(deps, [C1], turn_proxies=TP3)
edit(deps, lambda n: (n.get("turn") or {}).pop(S10, None))
for _ in range(N):
    sync(deps, [B1], turn_proxies=TP3)                    # the pool hands B out again
check("moving BACK to an address given up on asks again at once",
      ((rec(deps).get("turn") or {}).get(S10) or {}).get("listen") == B1 + ":56010", rec(deps).get("turn"))
save(deps, A2)
check("a pin forgets the node's asks", not [k for k in P._INGRESS_TP_TRIED if k[0] == X], sorted(P._INGRESS_TP_TRIED))

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
