#!/usr/bin/env python3
"""Self-test — the panel's speed limits (docs/LIMITS-PLAN.md §3.4, refresh R6–R8, R13, "limits-l2 design"; card limits-l2).

  [1] limits_clean: {d, u} or {c} in Mbit/s, 1..100000; {} / None = none; a rate under 1, a string, a bool, `c` beside
      `d`, an unknown key are refused with a perr sentence.
  [2] Every whitelist writer keeps `limits` (and `volume` on the three that hold it) through an unrelated save: user_set
      (a rename), group_set (a rename, a member change), peer_set (a title), clean_target (an address edit through
      peer_set) — a save that dropped one would lift a limit without a word.
  [3] Precedence: the target's own > the device's > the user's (pool u:<uid>) > the lowest of the user's groups (pool
      g:<gid>; download first, then upload); a user with no limit and no limited group gets no entry.
  [4] The wire: a wg/awg deployment's prefixes are the allowed_ips desired_for_node just gave it (a network behind it
      included), a cut device (blocked) is absent, an IPv6 prefix is not sent, a keyless deployment one entry per device
      keyless_sources vouches for; sorted.
  [5] No limit anywhere: [] without walking a peer (_peers_on is never called); the precedence is built once per roster
      revision on the shared view.
  [6] Real panels: with no limit the sync reply is byte-identical to origin/dev's build (8edb7878) (but what two
      instances of that build disagree on); the doors (users/update, groups/update, peers/update, update-target) store a
      limit and refuse a bad one; then the reply of the node a limit lands on carries `limits`, another node's does not.

Run: python3 tests/limits_panel_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED (exit 0 when caught):
     target     clean_target drops `limits`
     user       user_set drops `limits` on a rename
     group      group_set drops `limits`
     peer       peer_set drops `limits`
     highest    a user in two groups takes the HIGHER limit
     owntarget  the target's own limit is ignored
     cutpeer    the wire takes the target's address, not desired_for_node's (a cut device gets an entry)
     v6         IPv6 prefixes are sent
     keyalways  the reply carries `limits` even when empty
     door       update-target ignores `limits`
     twopath    a device's own limit on two paths is one policer a path
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
REF = "8edb7878"                                  # origin/dev before the limits: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PLANTS = {
    "target": ('''    lim = limits_clean(t.get("limits"))[0]
    if lim:
        out["limits"] = lim
    return out''', '''    return out'''),
    "user": ('''    for k in ("limits", "volume"):
        v = fields.get(k, u.get(k))''', '''    for k in ("volume",):
        v = fields.get(k, u.get(k))'''),
    "group": ('''    for k in ("limits", "volume"):                    # docs/LIMITS-PLAN.md §3.4: carried''',
              '''    for k in ("volume",):                    # docs/LIMITS-PLAN.md §3.4: carried'''),
    "peer": ('''"p2p_port", "limits", "volume"):''', '''"p2p_port", "volume"):'''),
    "highest": ('''_lim_key(lim) < _lim_key(eff[uid][0])''', '''_lim_key(lim) > _lim_key(eff[uid][0])'''),
    "owntarget": ('''            tl = limits_clean(t.get("limits"))[0]''', '''            tl = {}'''),
    "cutpeer": ('''                pairs = {t.get("iface") or "": [x.strip() for x in given.get((t.get("iface"), p.get("pubkey")), "").split(",")]}''',
                '''                pairs = {t.get("iface") or "": [(t.get("ip") or "").split("/")[0] + "/32"]}'''),
    "v6": ('''                nets = [n for n in nets if n and ":" not in n]''', '''                nets = [n for n in nets if n]'''),
    "keyalways": ('''**({"limits": _lims} if (_lims := limits_for_node(roster, nid, desired, snap)) else {}),''',
                  '''**({"limits": limits_for_node(roster, nid, desired, snap)}),'''),
    "twopath": ('''            if not pool and len(pairs) > 1:''', '''            if False:'''),
    "door": ('''            if has_lim:
                t["limits"] = _tlim''', '''            if False:
                t["limits"] = _tlim'''),
}

TMP = tempfile.mkdtemp(prefix="swg-limits-panel-")
SRC = open(PANEL, encoding="utf-8").read()
if PLANT:
    cut, new = PLANTS[PLANT]
    assert SRC.count(cut) == 1, "plant anchor for %s missing or not unique — would FALSE-PASS" % PLANT
    SRC = SRC.replace(cut, new, 1)
NEW = os.path.join(TMP, "swg-panel-server")
open(NEW, "w", encoding="utf-8").write(SRC)


def load(path, name):
    ld = importlib.machinery.SourceFileLoader(name, path)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m


P = load(NEW, "swgpanel_limits")
K = ["a" * 43 + "=", "b" * 43 + "=", "c" * 43 + "=", "d" * 43 + "=", "e" * 43 + "=", "f" * 43 + "="]


def guarded(name, fn):
    try:
        fn()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(name + " (raised)", False, "%s: %s" % (type(e).__name__, e))


# ── [1] the cleaner ─────────────────────────────────────────────────────────────────────────────────────────────────
def sec1():
    print("[1] limits_clean")
    ok = {"{d,u}": ({"d": 20, "u": 5}, {"d": 20, "u": 5}), "{c}": ({"c": 10.5}, {"c": 10.5}), "{d}": ({"d": 1}, {"d": 1}),
          "float integral": ({"d": 20.0}, {"d": 20}), "{}": ({}, {}), "None": (None, {})}
    for n, (raw, want) in ok.items():
        got, why = P.limits_clean(raw)
        check("[1] %s → %s" % (n, want), got == want and why is None, (got, why))
    for n, raw in {"under 1": {"d": 0.5}, "zero": {"d": 0}, "string": {"d": "10"}, "bool": {"d": True},
                   "c beside d": {"c": 5, "d": 5}, "unknown key": {"x": 5}, "a list": [10], "over the top": {"c": 100001},
                   "NaN": {"d": float("nan")}}.items():
        got, why = P.limits_clean(raw)
        check("[1] refused: %s" % n, got == {} and isinstance(why, dict) and why.get("error"), (got, why))


# ── [2] the whitelists ──────────────────────────────────────────────────────────────────────────────────────────────
def sec2():
    print("[2] every writer keeps the limits through an unrelated save")
    vol = {"c": 10 ** 10, "period": "m", "at": "cut"}
    r = {"users": {}, "peers": {}, "groups": {}}
    P.user_set(r, "u1", {"name": "A"}, 1)
    r["users"]["u1"].update(limits={"d": 20}, volume=vol)
    P.user_set(r, "u1", {"name": "A2"}, 2)
    check("[2] user_set: a rename keeps limits and volume", r["users"]["u1"].get("limits") == {"d": 20}
          and r["users"]["u1"].get("volume") == vol, r["users"]["u1"])
    P.user_set(r, "u1", {"limits": {}}, 3)
    check("[2] user_set: {} clears the limit (and only it)", "limits" not in r["users"]["u1"] and r["users"]["u1"].get("volume") == vol)
    P.group_set(r, "g1", {"name": "G", "users": ["u1"]})
    r["groups"]["g1"].update(limits={"c": 40}, volume=vol)
    P.group_set(r, "g1", {"name": "G2"})
    P.group_set(r, "g1", {"users": []})
    check("[2] group_set: a rename and a member change keep limits and volume",
          r["groups"]["g1"].get("limits") == {"c": 40} and r["groups"]["g1"].get("volume") == vol, r["groups"]["g1"])
    P.peer_set(r, "p1", {"title": "t", "pubkey": K[0], "targets": [{"node": "n1", "iface": "awg2", "ip": "10.9.0.2",
                                                                      "limits": {"d": 7}}]}, 1)
    r["peers"]["p1"].update(limits={"u": 3}, volume=vol)
    P.peer_set(r, "p1", {"title": "t2"}, 2)
    p = r["peers"]["p1"]
    check("[2] peer_set: a title keeps the device's limits and volume", p.get("limits") == {"u": 3} and p.get("volume") == vol, p)
    check("[2] clean_target: the deployment's own limit survives peer_set", p["targets"][0].get("limits") == {"d": 7}, p["targets"])
    P.peer_set(r, "p1", {"targets": [dict(t, ip="10.9.0.9") for t in p["targets"]]}, 3)   # an address edit, as F28's Deploy does
    check("[2] clean_target: an address edit keeps it", r["peers"]["p1"]["targets"][0].get("limits") == {"d": 7}, r["peers"]["p1"]["targets"])
    t = P.clean_target({"node": "n1", "iface": "awg2", "ip": "10.9.0.2", "limits": {"d": 0.2}})
    check("[2] clean_target: a stored bad limit (a hand edit) reads as none", "limits" not in t, t)


# ── [3]–[5] precedence and the wire ─────────────────────────────────────────────────────────────────────────────────
def roster():
    r = {"users": {}, "peers": {}, "groups": {}}
    for uid, nm in (("ua", "A"), ("ub", "B"), ("uc", "C"), ("ud", "D")):
        P.user_set(r, uid, {"name": nm}, 1)
    r["users"]["ua"]["limits"] = {"c": 30}
    P.group_set(r, "g1", {"name": "G1", "users": ["ub", "ud"]})
    P.group_set(r, "g2", {"name": "G2", "users": ["ub"]})
    r["groups"]["g1"]["limits"] = {"c": 40}
    r["groups"]["g2"]["limits"] = {"d": 20, "u": 5}

    def peer(pid, uid, key, ip, iface="awg2", node="n1", **kw):
        P.peer_set(r, pid, {"user_id": uid, "pubkey": key, "psk": "", "title": pid,
                            "targets": [{"node": node, "iface": iface, "ip": ip, **kw.pop("t", {})}], **kw}, 1)
    peer("pa1", "ua", K[0], "10.9.0.2")                               # the user's pool
    peer("pa2", "ua", K[1], "10.9.0.3", limits={"d": 8})              # the device's own
    peer("pb", "ub", K[2], "10.9.0.4", t={"limits": {"u": 2}})        # the deployment's own
    peer("pb2", "ub", K[3], "10.9.0.5")                               # two groups: the lower
    peer("pc", "uc", K[4], "10.9.0.6")                                # nothing
    peer("pd", "ud", K[5], "10.8.0.7", iface="wg1")                   # one group
    return r


def sec3():
    print("[3] precedence")
    r = roster()
    w = P.limits_for_node(r, "n1", P.desired_for_node(r, "n1"))
    got = {tuple(e[1]): e for e in w}
    check("[3] the user's own limit is its pool", got.get(("10.9.0.2/32",)) == ["awg2", ["10.9.0.2/32"], 0, 0, 30, "u:ua"], got)
    check("[3] the device's own beats the user's", got.get(("10.9.0.3/32",)) == ["awg2", ["10.9.0.3/32"], 8, 0, 0, ""], got)
    check("[3] the deployment's own beats everything", got.get(("10.9.0.4/32",)) == ["awg2", ["10.9.0.4/32"], 0, 2, 0, ""], got)
    check("[3] two limited groups: the lower (download 20 < 40)",
          got.get(("10.9.0.5/32",)) == ["awg2", ["10.9.0.5/32"], 20, 5, 0, "g:g2"], got)
    check("[3] one group", got.get(("10.8.0.7/32",)) == ["wg1", ["10.8.0.7/32"], 0, 0, 40, "g:g1"], got)
    check("[3] no limit, no entry", ("10.9.0.6/32",) not in got and len(w) == 5, w)
    check("[3] sorted by device then prefix", w == sorted(w, key=lambda e: (e[0], e[1])))


def sec4():
    print("[4] the wire")
    r = roster()
    desired = P.desired_for_node(r, "n1")
    for e in desired["awg2"]:
        if e["public_key"] == K[1]:
            e["allowed_ips"] = "10.9.0.3/32,192.168.50.0/24,fd00::/64"   # a network behind it, and an IPv6 one
    w = P.limits_for_node(r, "n1", desired)
    e = next((x for x in w if x[1][0] == "10.9.0.3/32"), None)
    check("[4] the prefixes are what desired_for_node gave (a network included), IPv6 left out",
          e is not None and e[1] == ["10.9.0.3/32", "192.168.50.0/24"], e)
    r["peers"]["pa1"]["disabled"] = True
    w = P.limits_for_node(r, "n1", P.desired_for_node(r, "n1"))
    check("[4] a cut device (blocked) gets no entry", not any(x[1] == ["10.9.0.2/32"] for x in w), w)
    P.peer_set(r, "pk", {"user_id": "ua", "pubkey": "", "wdtt_password": "pw1", "title": "k",
                         "targets": [{"node": "n1", "iface": "wdtt1", "ip": "", "type": "wdtt"}]}, 1)
    seen = []
    real = P.keyless_sources
    P.keyless_sources = lambda p, t, idx: (seen.append(t.get("iface")) or
                                           ([("wdtt1", "10.66.0.2/32"), ("wdtt1r", "10.67.0.2/32")], ""))
    try:
        w = P.limits_for_node(r, "n1", P.desired_for_node(r, "n1"), {"wdtt": []})
    finally:
        P.keyless_sources = real
    ks = [x for x in w if x[0].startswith("wdtt1")]
    check("[4] a keyless deployment: one entry per device keyless_sources vouches for, in its user's pool",
          seen == ["wdtt1"] and ks == [["wdtt1", ["10.66.0.2/32"], 0, 0, 30, "u:ua"], ["wdtt1r", ["10.67.0.2/32"], 0, 0, 30, "u:ua"]], (seen, ks))
    r["peers"]["pk"]["limits"] = {"d": 8}            # its own limit: one budget for both paths (limits-l1 F17)
    P.keyless_sources = lambda p, t, idx: ([("wdtt1", "10.66.0.2/32"), ("wdtt1r", "10.67.0.2/32")], "")
    try:
        w = P.limits_for_node(r, "n1", P.desired_for_node(r, "n1"), {"wdtt": []})
    finally:
        P.keyless_sources = real
    ks = [x for x in w if x[0].startswith("wdtt1")]
    check("[4] a device's own limit on two paths is one pool (t:<hash>), not one policer a path",
          len(ks) == 2 and ks[0][5] == ks[1][5] and ks[0][5].startswith("t:") and ks[0][2] == 8
          and len(ks[0][5]) <= 64, ks)


def sec5():
    print("[5] no limit anywhere")
    r = roster()
    for x in list(r["users"].values()) + list(r["groups"].values()) + list(r["peers"].values()):
        x.pop("limits", None)
    for p in r["peers"].values():
        for t in p["targets"]:
            t.pop("limits", None)
    real = P._peers_on
    calls = []
    P._peers_on = lambda *a: calls.append(a) or real(*a)
    try:
        w = P.limits_for_node(r, "n1", P.desired_for_node(r, "n1"))
    finally:
        P._peers_on = real
    check("[5] [] without walking the node's peers", w == [] and len(calls) == 1, (w, len(calls)))   # (the 1 is desired_for_node's)
    path = os.path.join(TMP, "users.json")
    json.dump(roster(), open(path, "w"))
    v, _m = P.roster_view(path)
    a = P._lim_index(v)
    check("[5] the precedence is built once per revision (the view's slot)", P._lim_index(v) is a and v.lim is a)
    time.sleep(0.01)
    rr = roster(); rr["users"]["ua"]["limits"] = {"c": 99}
    json.dump(rr, open(path, "w"))
    v2, _m2 = P.roster_view(path)
    check("[5] a save → a new view → built again", v2 is not v and P._lim_index(v2)["user"]["ua"][0] == {"c": 99})


# ── [6] real panels ─────────────────────────────────────────────────────────────────────────────────────────────────
def start_panel(src_path, tag, users):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    nodes = os.path.join(state, "nodes.json")
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {}},
               "n2": {"id": "n2", "name": "n2", "links": {}, "ifaces": {}}}, open(nodes, "w"))
    json.dump(users, open(os.path.join(state, "users.json"), "w"))
    fleet = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1"})
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                raise RuntimeError("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return p, port


def req(port, path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            out, code = resp.read(), resp.status
            if resp.headers.get("Content-Encoding") == "gzip":
                out = gzip.decompress(out)
    except urllib.error.HTTPError as e:
        out, code = e.read(), e.code
    return code, json.loads(out or b"{}")


def sync(port, tok, nid):
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


PROCS = []


def sec6():
    print("[6] real panels")
    r = roster()
    for x in list(r["users"].values()) + list(r["groups"].values()) + list(r["peers"].values()):
        x.pop("limits", None)
    for p in r["peers"].values():
        for t in p["targets"]:
            t.pop("limits", None)
    ref = os.path.join(TMP, "ref-swg-panel-server")
    open(ref, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True, check=True).stdout)
    ports = []
    for src, tag in ((ref, "refa"), (ref, "refb"), (NEW, "new")):
        p, port = start_panel(src, tag, r)
        PROCS.append(p)
        ports.append(port)
    toks = {port: {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("n1", "n2")} for port in ports}
    ra, rb, rn = (sync(port, toks[port]["n1"], "n1") for port in ports)
    ra, rb, rn = (sync(port, toks[port]["n1"], "n1") for port in ports)
    vol = {k for k in set(ra) | set(rb) if json.dumps(ra.get(k), sort_keys=True) != json.dumps(rb.get(k), sort_keys=True)}
    diff = [k for k in set(ra) | set(rn) if k not in vol and json.dumps(ra.get(k)) != json.dumps(rn.get(k))]
    check("[6] no limit: the sync reply is byte-identical to %s's (but what its own instances disagree on: %s)" % (REF, sorted(vol)),
          list(rn) == list(ra) and not diff and rn.get("desired"), (diff, set(rn) ^ set(ra)))
    port = ports[2]
    c, o = req(port, "/api/users/update", {"id": "ua", "limits": {"d": 0.5}})
    check("[6] users/update refuses a rate under 1", c == 400 and "between 1" in (o.get("error") or ""), (c, o))
    c, o = req(port, "/api/users/update", {"id": "ua", "limits": {"c": 30}})
    check("[6] users/update stores a limit", c == 200 and o["data"].get("limits") == {"c": 30}, (c, o))
    c, o = req(port, "/api/groups/update", {"id": "g2", "limits": {"d": 20, "u": 5}})
    check("[6] groups/update stores a limit", c == 200 and o["data"].get("limits") == {"d": 20, "u": 5}, (c, o))
    c, o = req(port, "/api/peers/update", {"peer_id": "pa2", "limits": {"d": 8}})
    check("[6] peers/update stores a limit", c == 200 and o["data"].get("limits") == {"d": 8}, (c, o))
    c, o = req(port, "/api/peers/update-target", {"peer_id": "pb", "node": "n1", "iface": "awg2", "limits": {"u": 2}})
    check("[6] update-target stores the deployment's own", c == 200 and o["data"]["targets"][0].get("limits") == {"u": 2}, (c, o))
    c, o = req(port, "/api/peers/update-target", {"peer_id": "pb", "node": "n1", "iface": "awg2", "limits": {"c": 2, "u": 1}})
    check("[6] update-target refuses a bad one", c == 400, (c, o))
    r1, r2 = sync(port, toks[port]["n1"], "n1"), sync(port, toks[port]["n2"], "n2")
    got = {tuple(e[1]): e for e in (r1.get("limits") or [])}
    check("[6] the node the limits land on gets them", got.get(("10.9.0.2/32",)) == ["awg2", ["10.9.0.2/32"], 0, 0, 30, "u:ua"]
          and got.get(("10.9.0.3/32",)) == ["awg2", ["10.9.0.3/32"], 8, 0, 0, ""]
          and got.get(("10.9.0.4/32",)) == ["awg2", ["10.9.0.4/32"], 0, 2, 0, ""]
          and got.get(("10.9.0.5/32",)) == ["awg2", ["10.9.0.5/32"], 20, 5, 0, "g:g2"], r1.get("limits"))
    check("[6] a node none lands on: no key", "limits" not in r2, r2.get("limits"))


try:
    for n, f in (("[1]", sec1), ("[2]", sec2), ("[3]", sec3), ("[4]", sec4), ("[5]", sec5), ("[6]", sec6)):
        guarded(n, f)
finally:
    for p in PROCS:
        p.terminate()
    for p in PROCS:
        try:
            p.wait(10)
        except Exception:
            p.kill()
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%s — %d failure(s)" % ("FAIL" if FAILS else "PASS", len(FAILS)))
if PLANT:
    print("PLANT %s: %s" % (PLANT, "caught (RED)" if FAILS else "NOT CAUGHT"))
    sys.exit(0 if FAILS else 1)
sys.exit(1 if FAILS else 0)
