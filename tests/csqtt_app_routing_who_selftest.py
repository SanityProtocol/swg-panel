#!/usr/bin/env python3
"""Self-test: csqtt 2.5 App routing EXCEPTIONS — per device / user / group (docs/CSQTT-APP-ROUTING-WHO-PLAN.md).

A 2.5 server's record may carry `app_routing_except`: [{who: {users, groups, peers}, app_routing: body | null}]. The panel
resolves it into each password's own `app_routing` (a device's entry beats its user's, a user's a group's; the upper group a
lower one; null = no App routing = the canonical all-default body), the node writes that into desired.json, and the 2.5
binary's `swgpanel_apply_routing` gives each password its rule. Section [4] runs the binary's own decision, ported from
forks/csqtt/2.5/csqtt-swgpanel-2.5.1-2.patch (`swgpanel_app_rule`, `swgpanel_apply_routing`, serde's reading), over the
desired.json the node writes — the outcome is judged by the engine, not by the panel's idea of it.

  [1] the door (_validate_ar_except): null kept as no App routing, an all-default own rule is the same; an own rule's
      refusal names the exception and nests the reason; nobody chosen, a cap of 20, a non-list are refused; a NEW unknown
      id is refused, a STORED one that dangles is dropped quietly and an entry left naming nobody goes
  [2] resolution (desired_csqtt_for_node): device > user > group, the upper group for a person in two, a deleted group
      names nobody, no winner → no key; per server (another server on the node keeps its own rule); a 2.1 server never
      resolves a list; the reply never carries the list
  [3] the node (_csqtt_desired_body): a password's own body written, its known keys only; a malformed one dropped from
      that password only; the drift check sees an exception added and removed; snap reports csqtt_ar_pw
  [4] the engine: each password's rule, as the 2.5 binary computes it from the node's desired.json, is the one asked for
      — incl. "No App routing" overriding a server rule, and removing the exception returning the server's rule
  [5] byte-identical: with no exceptions the sync reply and desired.json are those of 0c910315 (the panel and noded
      before this change), on a fleet with a 2.1 server, a 2.5 server with a rule and one without
  [6] through a real panel: /api/csqtt/set stores the list (2.5), refuses it on 2.1 and pops it on a switch to 2.1,
      keeps it when a tab does not send the key; csqtt_cfg publishes it; the node's sync reply carries per-password bodies
      and never the list

Run: python3 tests/csqtt_app_routing_who_selftest.py   (0 = pass)
     --perturb-null     "No App routing" sent as null (the binary reads it as the server's rule) → RED in [2]/[4]/[6]
     --perturb-order    a group's entry before a user's → RED in [2]/[4]
     --perturb-lastgrp  the LOWER group wins for a person in two → RED in [2]/[4]
     --perturb-nopop    the reply carries the list → RED in [2]/[6]
     --perturb-line21   a 2.1 server resolves a list too → RED in [2]
     --perturb-door     a stored id that dangles is refused (the server becomes unsavable) → RED in [1]
     --perturb-newid    a new unknown id is stored → RED in [1]
     --perturb-nodrop   the node writes a malformed per-password body → RED in [3]
     --perturb-nopass   the node drops per-password bodies (the old whitelist) → RED in [3]/[4]
     --perturb-cfg      csqtt_cfg does not publish the list → RED in [6]
     --perturb-keep21   a switch to 2.1 keeps the list → RED in [6]
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, types
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
BASE = "0c910315"   # the panel and noded before exceptions — [5] compares with them

P_PLANTS = {
    "--perturb-null": (("[2]", "[4]", "[6]"), '        body = e.get("app_routing") or _AR_NONE\n', '        body = e.get("app_routing")\n'),
    "--perturb-order": (("[2]", "[4]"), "                own = by[0].get(pid) or (uid and (by[1].get(uid) or by[2].get(uid)))",
                        "                own = by[0].get(pid) or (uid and (by[2].get(uid) or by[1].get(uid)))"),
    "--perturb-lastgrp": (("[2]", "[4]"), "                by[2].setdefault(uid, body)", "                by[2][uid] = body"),
    "--perturb-nopop": (("[2]", "[6]"), '        merged.pop("app_routing_except", None)', '        pass'),
    "--perturb-line21": (("[2]",), ' and str(r.get("line") or CSQTT_DEFAULT_LINE) != CSQTT_DEFAULT_LINE}', '}'),
    "--perturb-door": (("[1]",), "        if any(x not in known[k] and x not in stored[k] for k, ids in lists.items() for x in ids):",
                       "        if any(x not in known[k] for k, ids in lists.items() for x in ids):"),
    "--perturb-newid": (("[1]",), "        if any(x not in known[k] and x not in stored[k] for k, ids in lists.items() for x in ids):",
                        "        if False:"),
    "--perturb-cfg": (("[6]",), '"app_routing", "app_routing_except") if k in ov}', '"app_routing") if k in ov}'),
    "--perturb-keep21": (("[6]",), '            inst.pop("app_routing_except", None)     # …nor its exceptions\n', ''),
}
N_PLANTS = {
    "--perturb-nodrop": (("[3]",), '        own = _csqtt_app_routing(e.get("app_routing")) if "app_routing" in e else None',
                         '        own = e.get("app_routing")'),
    "--perturb-nopass": (("[3]", "[4]"), '        if own:\n            rec["app_routing"] = own\n', ''),
}
MODE = next((a for a in sys.argv[1:] if a in P_PLANTS or a in N_PLANTS), None)
SECTION = [""]
FAILS = []
def section(s):
    SECTION[0] = s; print(s, flush=True)
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="csqtt-ar-who-")

def source(path, plants):
    src = open(path, encoding="utf-8").read()
    if MODE in plants:
        _s, cut, new = plants[MODE]
        # ⚠️ ASSERT THE ANCHOR. A perturbation that matches nothing leaves a clean pass behind.
        assert src.count(cut) == 1, "perturbation anchor for %s matched %d times — would FALSE-PASS" % (MODE, src.count(cut))
        src = src.replace(cut, new, 1)
    return src

def load(src, name, path):
    m = types.ModuleType(name)
    m.__dict__.update({"__name__": name, "__file__": path})
    exec(compile(src.split("\nif __name__ ==")[0], os.path.basename(path), "exec"), m.__dict__)
    return m

PSRC, NSRC = source(PANEL, P_PLANTS), source(NODED, N_PLANTS)
P, N = load(PSRC, "p", PANEL), load(NSRC, "n", NODED)
def git_show(f):
    r = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (BASE, f)], capture_output=True, text=True)
    assert r.returncode == 0, "cannot read %s at %s: %s" % (f, BASE, r.stderr[:200])
    return r.stdout
P0, N0 = load(git_show("swg-panel-server"), "p0", PANEL), load(git_show("swg-noded"), "n0", NODED)
for m in (P, P0):
    m._turn_hold_get = lambda *a: None
SNAP = {"csqtt_lines": ["2.1", "2.5"]}

# ── the 2.5 binary's decision, ported (patch: SwgAppRouting / swgpanel_app_rule / SwgDesiredPw / swgpanel_apply_routing) ──
class Rejected(Exception):
    pass
_AR_TYPES = {"apps_mode": str, "packages": list, "domains_mode": str, "domains": list, "template_domains": bool,
             "ips_mode": str, "ips": list}
def serde_ar(r):
    """serde's reading of an `Option<SwgAppRouting>`: absent or null → None; every field #[serde(default)]; a wrong type
    rejects the whole file; unknown keys ignored."""
    if r is None:
        return None
    if not isinstance(r, dict):
        raise Rejected("app_routing not an object")
    out = {}
    for k, t in _AR_TYPES.items():
        v = r.get(k, t())
        if not isinstance(v, t) or (t is list and not all(isinstance(x, str) for x in v)):
            raise Rejected("%s: wrong type" % k)
        out[k] = v
    return out
def eng_rule(r):
    """swgpanel_app_rule: the rule's content (no id), or None = no rule."""
    only = r["apps_mode"] == "only"
    packages = list(r["packages"]) if r["apps_mode"] in ("except", "only") else []
    dw = r["domains_mode"] == "tunnel"
    tpl = r["template_domains"] and not dw
    iw = r["ips_mode"] == "tunnel"
    if not packages and not only and not r["domains"] and not tpl and not dw and not r["ips"] and not iw:
        return None
    return {"is_whitelist": only, "packages": packages, "template_domains": tpl, "direct_domains": list(r["domains"]),
            "domains_is_whitelist": dw, "ip_is_whitelist": iw, "ips": list(r["ips"])}
def eng_apply(text):
    """swgpanel_apply_routing over a desired.json → {password: rule content or None (routing_rule_id "")}."""
    d = json.loads(text)
    srv = serde_ar(d.get("app_routing"))
    srv = eng_rule(srv) if srv else None
    out = {}
    for p in d.get("passwords") or []:
        own = serde_ar(p.get("app_routing"))
        out[p["password"]] = srv if own is None else eng_rule(own)
    return out

# ── fixture ──
SR = {"apps_mode": "all", "packages": [], "domains_mode": "direct", "domains": ["ya.ru"], "template_domains": True,
      "ips_mode": "direct", "ips": []}
SR2 = dict(SR, domains=["vk.com"], template_domains=False)
R_G1 = dict(SR, domains=["g1.ru"], template_domains=False)
R_G2 = dict(SR, domains=["g2.ru"], template_domains=False)
R_P2 = {"apps_mode": "only", "packages": ["org.telegram.messenger"], "domains_mode": "direct", "domains": [],
        "template_domains": False, "ips_mode": "direct", "ips": []}
R_X = dict(SR, domains=["x.ru"])
EXC = [{"who": {"groups": ["g2"]}, "app_routing": R_G2},
       {"who": {"groups": ["g1"]}, "app_routing": R_G1},
       {"who": {"users": ["u1"]}, "app_routing": None},
       {"who": {"peers": ["p2"]}, "app_routing": R_P2},
       {"who": {"groups": ["gone"]}, "app_routing": R_X}]
def peer(uid, pw, *ifs):
    return {"user_id": uid, "csqtt_password": pw, "targets": [{"node": "n1", "iface": i} for i in ifs]}
ROSTER = {"users": {"u1": {"name": "ann"}, "u2": {"name": "bob"}, "u3": {"name": "cid"}, "u4": {"name": "dan"}},
          "groups": {"g1": {"name": "one", "users": ["u2", "u4"]}, "g2": {"name": "two", "users": ["u1", "u2"]}},
          "peers": {"p1": peer("u1", "pw-a", "csqtt1", "csqtt2"), "p2": peer("u1", "pw-b", "csqtt1"),
                    "p3": peer("u2", "pw-c", "csqtt1"), "p4": peer("u3", "pw-d", "csqtt1"), "p5": peer(None, "pw-e", "csqtt1"),
                    "p6": peer("u4", "pw-f", "csqtt1", "csqtt3")}}
def fleet(exc=EXC, line1="2.5", ex3=None):
    c1 = {"listen": "0.0.0.0:46000", "tun_addr": "10.66.70.1/24", "line": line1, "app_routing": SR}
    if exc is not None:
        c1["app_routing_except"] = exc
    c3 = {"listen": "0.0.0.0:46020", "tun_addr": "10.66.72.1/24"}       # a 2.1 server (no line = 2.1)
    if ex3 is not None:
        c3["app_routing_except"] = ex3
    return {"n1": {"csqtt": {"csqtt1": c1, "csqtt2": {"listen": "0.0.0.0:46010", "tun_addr": "10.66.71.1/24", "line": "2.5",
                                                     "app_routing": SR2},
                             "csqtt3": c3}}}
OWN = lambda iface, pw, f=None: (P.desired_csqtt_for_node(ROSTER, f or fleet(), "n1").get(iface) or {}).get(pw, {})

try:
    section("[1] the door")
    V = P._validate_ar_except
    out, err = V([{"who": {"users": ["u1"]}, "app_routing": None},
                  {"who": {"groups": ["g1"], "peers": ["p2"]}, "app_routing": {"apps_mode": "all"}},
                  {"who": {"peers": ["p3"]}, "app_routing": {"domains": "www.ya.ru"}}], [], ROSTER)
    check("null is no App routing; an all-default own rule is the same; an own rule stored as the app applies it",
          err is None and [e["app_routing"] for e in out] == [None, None, dict(P._AR_NONE, domains=["ya.ru"])], (out, err))
    check("who keeps only its non-empty kinds, ids sorted", err is None and out[1]["who"] == {"groups": ["g1"], "peers": ["p2"]}, out)
    check("nothing is an empty list", V(None, [], ROSTER) == ([], None) and V([], [], ROSTER) == ([], None))
    o, e = V([{"who": {"users": ["u1"]}}, {"who": {"users": ["u2"]}, "app_routing": {"ips": ["2001:db8::/32"]}}], [], ROSTER)
    check("an own rule's refusal names the exception and nests the reason (translatable)",
          o is None and e and e["error_key"] == "Exception {v1}: {v2}" and e["error_vars"]["v1"] == "2"
          and "IPv4" in e["error_vars"]["v2"]["error_key"], e)
    for bad, key in (([{"who": {}}], "choose at least one"), ([{"who": {"users": []}, "app_routing": None}], "choose at least one"),
                     ([{"who": {"users": ["u1"]}}] * 21, "at most"), ({"who": {}}, "not a valid setting"),
                     ([{"who": {"users": "u1"}}], "not a valid setting"), ([{"who": {"users": ["nobody"]}}], "no longer exists")):
        o, e = V(bad, [], ROSTER)
        check("refused: %s" % key, o is None and e and key in e["error"], (str(bad)[:60], e))
    prev = [{"who": {"users": ["u1", "u9"], "groups": ["g9"]}, "app_routing": None}, {"who": {"groups": ["g8"]}, "app_routing": None}]
    o, e = V([{"who": {"users": ["u1", "u9"], "groups": ["g9"]}, "app_routing": None},
              {"who": {"groups": ["g8"]}, "app_routing": None}], prev, ROSTER)
    check("a stored id that no longer exists is dropped quietly (the server stays savable); an entry left naming nobody goes",
          e is None and o == [{"who": {"users": ["u1"]}, "app_routing": None}], (o, e))
    o, e = V([{"who": {"users": ["u1", "u7"]}}], prev, ROSTER)
    check("…while a NEW unknown id is refused", o is None and e and "no longer exists" in e["error"], (o, e))

    section("[2] resolution")
    def got(pw, iface="csqtt1", f=None):
        return OWN(iface, pw, f).get("app_routing", "ABSENT")
    check("a device's entry beats its user's (pw-b: p2's own rule, not u1's None)", got("pw-b") == R_P2, got("pw-b"))
    check("a user's entry beats a group's (pw-a: u1 is in g2, u1's None wins → the canonical all-default body)",
          got("pw-a") == P._AR_NONE, got("pw-a"))
    check("a person in two groups gets the upper one (pw-c: u2 in g1 and g2 → g2, listed first)", got("pw-c") == R_G2, got("pw-c"))
    check("a group's entry for its member (pw-f: u4 in g1)", got("pw-f") == R_G1, got("pw-f"))
    check("no winner → no key (pw-d: u3 in no group; pw-e: no user)", got("pw-d") == "ABSENT" and got("pw-e") == "ABSENT")
    check("a deleted group names nobody", all(got(pw) != R_X for pw in ("pw-a", "pw-b", "pw-c", "pw-d", "pw-e", "pw-f")))
    check("per server: p1 on csqtt2 (no exceptions) carries none", got("pw-a", "csqtt2") == "ABSENT", got("pw-a", "csqtt2"))
    check("a 2.1 server never resolves a list (a hand-edited one included)",
          got("pw-f", "csqtt3", fleet(ex3=[{"who": {"users": ["u4"]}, "app_routing": None}])) == "ABSENT"
          and got("pw-a", "csqtt1", fleet(line1="2.1")) == "ABSENT")
    rep = P._csqtt_reply(ROSTER, fleet(), "n1", snap=SNAP)
    check("the reply never carries the list", all("app_routing_except" not in (v or {}) for v in rep.values()), list(rep.get("csqtt1", {})))
    check("…and its passwords carry the resolved bodies", (rep["csqtt1"]["passwords"].get("pw-b") or {}).get("app_routing") == R_P2)

    section("[3] the node")
    BODY = lambda pws, ar=SR: N._csqtt_desired_body({"passwords": pws, "app_routing": ar})
    d = json.loads(BODY({"pw-a": {"name": "a", "app_routing": dict(R_G1, bogus=1)}, "pw-b": {"name": "b"}}))
    check("a password's own body is written, its known keys only; the others have none",
          d["passwords"][0].get("app_routing") == R_G1 and "app_routing" not in d["passwords"][1], d)
    check("the canonical all-default body is written as it is (never dropped as empty)",
          json.loads(BODY({"pw-a": {"app_routing": P._AR_NONE}}))["passwords"][0].get("app_routing") == P._AR_NONE)
    for bad in (dict(R_G1, domains="g1.ru"), dict(R_G1, apps_mode="sometimes"), "x", None, {}):
        d = json.loads(BODY({"pw-a": {"app_routing": bad}, "pw-b": {"app_routing": R_G2}}))
        check("a malformed body drops from that password only: %s" % str(bad)[:40],
              "app_routing" not in d["passwords"][0] and d["passwords"][1].get("app_routing") == R_G2 and d.get("app_routing") == SR, d)
    N._csqtt_dir = lambda iface: TMP
    open(os.path.join(TMP, "desired.json"), "w").write(BODY({"pw-a": {}}) + "\n")
    check("the drift check sees an exception added", N._csqtt_desired_changed("csqtt1", BODY({"pw-a": {"app_routing": R_G1}})) is True)
    open(os.path.join(TMP, "desired.json"), "w").write(BODY({"pw-a": {"app_routing": R_G1}}) + "\n")
    check("…the same one is no change, and its removal is", N._csqtt_desired_changed("csqtt1", BODY({"pw-a": {"app_routing": R_G1}})) is False
          and N._csqtt_desired_changed("csqtt1", BODY({"pw-a": {}})) is True)
    check("the node reports csqtt_ar_pw", 'snap["csqtt_ar_pw"] = 1' in NSRC)

    section("[4] the engine")
    def engine(f=None, iface="csqtt1"):
        r = P._csqtt_reply(ROSTER, f or fleet(), "n1", snap=SNAP)[iface]
        return eng_apply(N._csqtt_desired_body(r))
    try:
        e4 = engine()
    except Rejected as ex:
        e4 = {"rejected": str(ex)}
    want = {"pw-a": None, "pw-b": eng_rule(serde_ar(R_P2)), "pw-c": eng_rule(serde_ar(R_G2)), "pw-d": eng_rule(serde_ar(SR)),
            "pw-e": eng_rule(serde_ar(SR)), "pw-f": eng_rule(serde_ar(R_G1))}
    for pw, w in want.items():
        check("%s gets %s" % (pw, "no rule" if w is None else (w["direct_domains"] or w["packages"])), e4.get(pw, "?") == w, e4.get(pw, "?"))
    check("\"No App routing\" overrides the server's rule (the server has one)", e4.get("pw-a", "?") is None and e4.get("pw-d") is not None)
    e5 = engine(fleet(exc=[e for e in EXC if e["who"] != {"users": ["u1"]}]))
    check("removing the exception gives the server's rule back (pw-a: u1's entry gone → its group g2)", e5.get("pw-a") == want["pw-c"], e5.get("pw-a"))
    e6 = engine(fleet(exc=None))
    check("no exceptions: every password gets the server's rule", all(v == want["pw-d"] for v in e6.values()) and len(e6) == 6, e6)
    e7 = eng_apply(N._csqtt_desired_body(P._csqtt_reply(ROSTER, fleet(), "n1", snap=SNAP)["csqtt2"]))
    check("another server keeps its own rule", e7 == {"pw-a": eng_rule(serde_ar(SR2))}, e7)

    section("[5] byte-identical without exceptions (vs %s)" % BASE)
    import copy
    for label, f in (("2.1 + 2.5 with a rule + 2.5 without", fleet(exc=None)),
                     ("…with the 2.5 server's rule gone", {"n1": {"csqtt": {k: {x: y for x, y in v.items() if x != "app_routing"}
                                                                          for k, v in fleet(exc=None)["n1"]["csqtt"].items()}}})):
        a = json.dumps(P._csqtt_reply(copy.deepcopy(ROSTER), copy.deepcopy(f), "n1", snap=SNAP), sort_keys=False)
        b = json.dumps(P0._csqtt_reply(copy.deepcopy(ROSTER), copy.deepcopy(f), "n1", snap=SNAP), sort_keys=False)
        check("the sync reply: %s" % label, a == b, (a[:200], b[:200]))
        for iface, inst in json.loads(a).items():
            check("desired.json %s: %s" % (iface, label), N._csqtt_desired_body(inst) == N0._csqtt_desired_body(inst))
    a = P._csqtt_reply(ROSTER, fleet(), "n1", snap=SNAP)
    b = P0._csqtt_reply(ROSTER, fleet(exc=None), "n1", snap=SNAP)
    check("exceptions on one server leave the others' replies as they were", a["csqtt2"] == b["csqtt2"] and a["csqtt3"] == b["csqtt3"])

    section("[6] through a real panel")
    server = PANEL
    if MODE in P_PLANTS:
        server = os.path.join(TMP, "swg-panel-server"); open(server, "w", encoding="utf-8").write(PSRC)
    state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
    NODES = os.path.join(state, "nodes.json")
    f = fleet(exc=None)
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {}, "csqtt": f["n1"]["csqtt"]}}, open(NODES, "w"))
    json.dump(ROSTER, open(os.path.join(state, "users.json"), "w"))
    fj = os.path.join(TMP, "fleet.json")
    json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fj, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
    log = open(os.path.join(TMP, "panel.log"), "w+")
    proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "SWG_PANEL_FLEET": fj, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                 "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                 "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
    def req(path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                                   headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw, code = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            raw, code = e.read(), e.code
        try:
            return code, json.loads(raw or b"{}")
        except Exception:
            return code, {"raw": raw[:200]}
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
            except Exception:
                if proc.poll() is not None:
                    sys.exit("panel exited: " + open(log.name).read()[-2000:])
                time.sleep(0.1)
        tok = req("/api/nodes/rotate", {"id": "n1"})[1]["data"]["token"]
        rec = lambda i="csqtt1": (json.load(open(NODES))["n1"].get("csqtt") or {}).get(i) or {}
        SET = lambda **b: req("/api/csqtt/set", dict({"node": "n1", "iface": "csqtt1"}, **b))
        code, r = SET(app_routing=SR, app_routing_except=[{"who": {"users": ["u1"]}, "app_routing": None},
                                                          {"who": {"peers": ["p2"]}, "app_routing": R_P2}])
        check("a 2.5 server stores the list", code == 200 and rec().get("app_routing_except") == [
            {"who": {"users": ["u1"]}, "app_routing": None}, {"who": {"peers": ["p2"]}, "app_routing": R_P2}], (code, r, rec()))
        code, r = SET(title="x")
        check("a tab that does not send the key keeps the list", code == 200 and len(rec().get("app_routing_except") or []) == 2, rec())
        code, r = SET(app_routing_except=[{"who": {"users": ["u1"]}, "app_routing": {"ips": ["2001:db8::/32"]}}])
        check("a refusal is a 400 naming the exception, the stored list stays",
              code == 400 and r.get("error_key") == "Exception {v1}: {v2}" and len(rec().get("app_routing_except") or []) == 2, (code, r))
        code, st = req("/api/state")
        cfg = ((next((n for n in (st.get("data") or st).get("nodes") or [] if n.get("id") == "n1"), {}) or {}).get("csqtt_cfg") or {}).get("csqtt1") or {}
        check("csqtt_cfg publishes the list (the sheet's prefill)", len(cfg.get("app_routing_except") or []) == 2, list(cfg))
        sn = {"hostname": "n1", "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}, "csqtt_lines": ["2.1", "2.5"],
              "csqtt_ar_pw": 1, "csqtt": [{"iface": i, "kind": "csqtt", "fork": "csqtt", "active": "active", "line": l}
                                           for i, l in (("csqtt1", "2.5"), ("csqtt2", "2.5"), ("csqtt3", "2.1"))]}
        code, r = req("/api/node/sync", {"snapshot": sn}, tok)
        c1 = (r.get("csqtt") or {}).get("csqtt1") or {}
        check("the sync reply carries per-password bodies and never the list",
              code == 200 and "app_routing_except" not in c1 and (c1.get("passwords", {}).get("pw-b") or {}).get("app_routing") == R_P2
              and (c1.get("passwords", {}).get("pw-a") or {}).get("app_routing") == P._AR_NONE, (code, list(c1)))
        code, r = req("/api/csqtt/set", {"node": "n1", "iface": "csqtt3", "app_routing_except": [{"who": {"users": ["u1"]}}]})
        check("a 2.1 server refuses the list", code == 400 and "app_routing_except" not in rec("csqtt3"), (code, r))
        code, r = SET(line="2.1")
        check("a switch to 2.1 pops the list with the rule", code == 200 and "app_routing_except" not in rec() and "app_routing" not in rec(), (code, rec()))
    finally:
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = (P_PLANTS.get(MODE) or N_PLANTS.get(MODE))[0]
    hit = [n for s, n in FAILS if s.startswith(secs)]
    stray = sorted({s.split(" ")[0] for s, n in FAILS if not s.startswith(secs)})
    print("\nperturb %s: %s" % (MODE, ("NOT caught by " + "/".join(secs)) if not hit
          else ("ALSO red outside its section(s): " + ", ".join(stray)) if stray else ("RED on " + "/".join(secs) + " as expected")))
    sys.exit(0 if hit and not stray else 1)
print("\n" + ("ALL PASS" if not FAILS else "%d FAIL: %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)
