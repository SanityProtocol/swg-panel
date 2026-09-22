#!/usr/bin/env python3
"""Self-test — AmneziaWG 3.1, the panel's half (docs/AWG3-PLAN.md §7.1–§7.3, gate G9).

An interface's generation is the dict the panel keeps for it: HeaderProtectionKey present ⇒ 3.1. The panel is asked for a
switch with `awg_gen` ("3.1" | "2.0", an intent, never stored) on /api/iface/update and /api/iface/create, and from then
on the sync loop converges the node to the dict. What must hold, each driven through a REAL panel process (temp state,
scratch port, no auth; the node's side is played by POSTing snapshots to /api/node/sync):

  [1] withhold — a node that does not report `datapath.awg.gen` is older than the 3.x keys and is never sent one
      (its agent would filter them, the readback would never match, the push would repeat every sync for ever)
  [2] refuse   — a switch or a 3.1 create on a node below 3.1 is a 400 naming the part: no report / tools / module /
      userspace fallback; a 3.1 node is let through
  [3] a switch over S3 = 11 re-draws S1–S4 (header protection refuses S < 12)
  [4] an Edit save of S4 = 11 on a 3.1 interface is a 400 naming S4
  [5] RekeyAfterTime 170-180 against RejectAfterTime 150-180 is a 400 naming both
  [6] a second switch to 3.1 keeps the HeaderProtectionKey (a new one would cut every client again)
  [7] a switch — and a 3.1 create — over a PARTIAL record stores the FULL dict, and the restore request built from it
      sends the same S/H (a record holding the 3.1 set alone would restore as "that + the agent's random 2.0 set")
  [8] synced means the whole generation matches: a HeaderProtectionKey the node still reports after a switch back is
      pushed away (with `awg_params_exact`, so the node drops it); once gone, the interface reads synced; a CONFIRMED
      2.0 record meeting an unexpected key is drift for the operator, never a push
  [9] a 2.0 interface is untouched by all of it: its sync reply carries no new field (see also the differential rig)
  [10] an older node (no `gen`) is asked for no switch in EITHER direction, and no 3.x set is queued for it by a create
       or a recreate: its agent can neither apply nor remove the keys (the review of 9f40ac2: a switch back there read
       as synced while the device kept its HPK)
  [11] a switch never carries DisableCookies (D-cookies), not even one the interface brought
  [12] a 3.x key at 0 / off is "unset" — dropped on save, never stored; an all-zero HeaderProtectionKey is refused

Run: python3 tests/awg3_panel_selftest.py                 (0 = pass)
     --perturb <name>   plants one regression in a copy of the panel and expects RED on its own section:
                        withhold [1] · refuse [2] · on-fallback [2] · redraw [3] · s12 [4] · timing [5] · hpk-once [6] ·
                        full [7] · presence [8] · exact [8] · old-node / old-node-create / old-node-recreate [10] · cookies [11] ·
                        zero [12]
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {   # name: (section it must redden, anchor, replacement)
    "withhold": ("[1]", "                if not awg_gen_reported(snap):\n                    want = {k: v for k, v in want.items() if k not in AWG3_FIELDS}\n",
                 "                if False:\n                    want = {k: v for k, v in want.items() if k not in AWG3_FIELDS}\n"),
    "refuse": ("[2]", "    g = {k: v for k, v in _awg_datapath(snap)[\"gen\"].items() if isinstance(v, str)}   # a version is a string; anything else is none\n",
               "    return None\n"),
    "on-fallback": ("[2]", "    on_fallback = bool(iface) and iface in (_awg_datapath(snap).get(\"userspace\") or [])\n",
                    "    on_fallback = False\n"),
    "old-node": ("[10]", "            if not awg_gen_reported((deps.get(\"node_snaps\") or {}).get(nid)):\n                return 400,",
                 "            if False:\n                return 400,"),
    "old-node-create": ("[10]", "        if any(k in _awgput for k in AWG3_FIELDS) and not awg_gen_reported((deps.get(\"node_snaps\") or {}).get(nid)):\n",
                        "        if False:\n"),
    "old-node-recreate": ("[10]", "        if any(k in (req.get(\"awg_params\") or {}) for k in AWG3_FIELDS) and not awg_gen_reported(snap):\n",
                          "        if False:\n"),
    "cookies": ("[11]", "if k in AWG_FIELDS and k != \"DisableCookies\" and v is not None", "if k in AWG_FIELDS and v is not None"),
    "zero": ("[12]", "            if out[k] == \"0\":\n                out.pop(k)", "            if False:\n                out.pop(k)"),
    "redraw": ("[3]", "    if any(not d.get(k, \"\").isdigit() or int(d[k]) < 12 for k in (\"S1\", \"S2\", \"S3\", \"S4\")):\n",
               "    if False:\n"),
    "s12": ("[4]", "        if low:\n            return None, perr(\"{v1} must be 12 or more while header protection is on\", v1=\", \".join(low))\n",
            ""),
    "timing": ("[5]", "        if tot > lo:\n", "        if False:\n"),
    "hpk-once": ("[6]", "    d.setdefault(\"HeaderProtectionKey\", base64.b64encode(os.urandom(32)).decode())\n",
                 "    d[\"HeaderProtectionKey\"] = base64.b64encode(os.urandom(32)).decode()\n"),
    "full": ("[7]", "    for k, v in {**AWG31_SET, **{k: v for k, v in (defaults or {}).items() if k in _AWG3_RANGED}}.items():\n        d.setdefault(k, v)\n",
             "    d = {k: v for k, v in d.items() if k in AWG3_FIELDS}\n    for k, v in AWG31_SET.items():\n        d.setdefault(k, v)\n"),
    "presence": ("[8]", "                elif not extra and all(str(ra.get(k)) == str(want[k]) for k in want):\n",
                 "                elif all(str(ra.get(k)) == str(want[k]) for k in want):\n"),
    "exact": ("[8]", "                        d[\"awg_params_exact\"] = True\n", "                        pass\n"),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:260]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="awg3-panel-")
server = SERVER
if MODE:
    _sec, old, new = PLANTS[MODE]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new))

_l = importlib.machinery.SourceFileLoader("swgpanel_awg3", server)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_awg3", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass

HPK = "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0="
BASE20 = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33",
          "H1": "103509605-103509620", "H2": "1694692368-1694692383", "H3": "2553282719-2553282734",
          "H4": "3170237912-3170237927", "I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>",
          "I4": "<b 0xc000000001><r 32><t>", "I5": "<t><r 48>"}
SET31 = {"HeaderProtectionKey": HPK, "RandomTrailers": "1", "ContentPaddingAddition": "10-100", "RekeyAfterTime": "100-120",
         "RekeyTimeout": "3-7", "RejectAfterTime": "150-180", "KeepaliveTimeout": "5-15", "MaxHandshakeAttempts": "15-20"}
FULL31 = {**BASE20, **SET31}
AWG3 = ("HeaderProtectionKey", "RandomTrailers", "ContentPaddingAddition", "RekeyAfterTime", "RekeyTimeout",
        "RejectAfterTime", "KeepaliveTimeout", "MaxHandshakeAttempts", "DisableCookies")
G31 = {"module": "3.1", "fallback": "3.1", "tools": "3.1"}
GENS = {"n31": G31, "n20": {"module": "2.0", "fallback": "3.1", "tools": "3.1"},
        "ntools": {"module": "3.1", "fallback": "3.1", "tools": "2.0"},
        "nfb": {"module": None, "fallback": "3.0", "tools": "3.1"}, "nold": None,
        "nnix": {"module": "2.0", "fallback": "2.0", "tools": "2.0"},        # what the nixos node reports (measured 09-19)
        "nus": {"module": "3.1", "fallback": "3.0", "tools": "3.1"}}          # its awg0 runs on the (3.0) fallback — see [2]
PUB = "8Y1mOEM2Uv3Ez6CUfXOvsUg0dNrV4kx0mB9rp1cV3lE="


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in GENS}, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
PORT = free_port()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                             "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                             "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})


def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
    try:
        return code, json.loads(raw or b"{}")
    except Exception:
        return code, {"raw": raw[:200]}

for _ in range(150):
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
    except Exception:
        if proc.poll() is not None:
            sys.exit("panel exited: " + open(log.name).read()[-2000:])
        time.sleep(0.1)
TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in GENS}


def nodes():
    return json.load(open(NODES))

def put_record(nid, iface, rec):
    """Plant an interface record the way a previous save left it — the panel re-reads nodes.json per request."""
    n = nodes(); n[nid].setdefault("ifaces", {})[iface] = rec
    with open(NODES + ".tmp", "w") as f:
        json.dump(n, f)
    os.replace(NODES + ".tmp", NODES)

def snap(nid, reported, iface="awg0"):
    s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t",
         "interfaces": {iface: {"peers": [], "meta": {"public_key": PUB, "listen_port": 51820, "mtu": 1280,
                                                      "subnet": "10.60.0.0/24", "address": "10.60.0.1/24",
                                                      "awg_params": reported, "tool": "awg"}}}}
    if GENS[nid] is not None:
        s["datapath"] = {"awg": {"gen": GENS[nid]}}
    if nid == "nus":                  # the module is loaded, but this interface fell back to userspace (plan D2 report)
        s["datapath"]["awg"].update({"needed": True, "ok": True, "userspace": [iface]})
    return s

def sync(nid, reported, iface="awg0"):
    code, r = req("/api/node/sync", {"snapshot": snap(nid, reported, iface)}, TOK[nid])
    assert code == 200, (code, r)
    return ((r.get("desired_ifaces") or {}).get(iface) or {})

def update(nid, iface="awg0", **body):
    return req("/api/iface/update", {"node": nid, "iface": iface, **body})

def ov(nid, iface="awg0"):
    return (nodes()[nid].get("ifaces") or {}).get(iface) or {}

def s_ok(d):
    return all(str(d.get(k, "")).isdigit() and int(d[k]) >= 12 for k in ("S1", "S2", "S3", "S4"))

try:
    SECTION[0] = "[1]"
    print("[1] an older node (no `gen`) is never sent a 3.x key")
    put_record("nold", "awg0", {"awg_params": {**FULL31, "Jc": "5"}})
    d = sync("nold", {**BASE20})                     # it reports 2.0 keys only (its AWG_KEYS knows no more) and Jc 4
    check("the old node is pushed the Jc change", str((d.get("awg_params") or {}).get("Jc")) == "5", d)
    check("…with no 3.x key in it", not any(k in (d.get("awg_params") or {}) for k in AWG3), d.get("awg_params"))
    d = sync("nold", {**BASE20, "Jc": "5"})
    check("…and once its 2.0 keys match, nothing more is pushed (no re-push for ever)", "awg_params" not in d, d)
    put_record("n31", "awg0", {"awg_params": {**FULL31, "Jc": "5"}})
    d = sync("n31", {**BASE20})
    check("control: a node that reports `gen` IS sent the 3.x keys", (d.get("awg_params") or {}).get("HeaderProtectionKey") == HPK, d)

    SECTION[0] = "[2]"
    print("\n[2] a switch or a 3.1 create below 3.1 is refused, naming the part")
    for nid, needle in (("nold", "does not report its AmneziaWG version"), ("n20", "kernel module is 2.0"),
                        ("ntools", "awg tools are AmneziaWG 2.0"), ("nfb", "amneziawg-go), which this interface would run on, is 3.0"),
                        ("nnix", "kernel module is 2.0")):
        put_record(nid, "awg0", {"awg_params": dict(BASE20)})
        sync(nid, dict(BASE20))
        code, r = update(nid, awg_gen="3.1")
        check("%s: switch → 400 naming %r" % (nid, needle), code == 400 and needle in (r.get("error") or ""), (code, r))
        check("%s: …and the record is untouched" % nid, ov(nid).get("awg_params") == BASE20, ov(nid).get("awg_params"))
        code, r = req("/api/iface/create", {"node": nid, "iface": "awgn", "subnet": "10.61.%d.0/24" % len(nid), "awg_gen": "3.1"})
        check("%s: 3.1 create → 400 naming it too" % nid, code == 400 and needle in (r.get("error") or ""), (code, r))
        check("%s: …and nothing was queued" % nid, "awgn" not in (nodes()[nid].get("create") or {}))
    put_record("nus", "awg0", {"awg_params": dict(BASE20)})
    sync("nus", dict(BASE20))
    code, r = update("nus", awg_gen="3.1")
    check("nus: module 3.1, but THIS interface runs on a 3.0 fallback → 400 naming amneziawg-go",
          code == 400 and "amneziawg-go), which this interface would run on, is 3.0" in (r.get("error") or ""), (code, r))
    put_record("n31", "awg0", {"awg_params": dict(BASE20)})
    sync("n31", dict(BASE20))
    code, r = update("n31", awg_gen="3.1")
    check("control: the 3.1 node's switch goes through", code == 200, (code, r))
    check("…and its record now holds the 3.1 set", all(k in ov("n31")["awg_params"] for k in SET31), ov("n31").get("awg_params"))
    code, r = update("n31", awg_gen="3.2")
    check("an awg_gen that is not 2.0 or 3.1 is a 400", code == 400, (code, r))

    SECTION[0] = "[3]"
    print("\n[3] a switch over S3 = 11 re-draws S1–S4")
    put_record("n31", "awg3", {"awg_params": {**BASE20, "S3": "11"}})
    sync("n31", {**BASE20, "S3": "11"}, "awg3")
    code, r = update("n31", "awg3", awg_gen="3.1")
    a = ov("n31", "awg3").get("awg_params") or {}
    check("the switch is accepted", code == 200, (code, r))
    check("S1–S4 are all ≥ 12 after it", s_ok(a), {k: a.get(k) for k in ("S1", "S2", "S3", "S4")})
    check("…S3 is no longer 11", a.get("S3") != "11", a.get("S3"))

    SECTION[0] = "[4]"
    print("\n[4] an Edit save of S4 = 11 on a 3.1 interface is refused, naming S4")
    put_record("n31", "awg4", {"awg_params": dict(FULL31)})
    code, r = update("n31", "awg4", awg_params={**FULL31, "S4": "11"})
    check("400 naming S4", code == 400 and "S4" in (r.get("error") or ""), (code, r))
    check("…the record keeps S4 = 33", ov("n31", "awg4")["awg_params"].get("S4") == "33", ov("n31", "awg4").get("awg_params"))
    code, r = update("n31", "awg4", awg_params={**BASE20, "S4": "11"})
    check("control: the same S4 = 11 on a 2.0 set is saved as before", code == 200, (code, r))

    SECTION[0] = "[5]"
    print("\n[5] RekeyAfterTime 170-180 against RejectAfterTime 150-180 is refused, naming both")
    put_record("n31", "awg5", {"awg_params": dict(FULL31)})
    code, r = update("n31", "awg5", awg_params={**FULL31, "RekeyAfterTime": "170-180"})
    e = r.get("error") or ""
    check("400 naming RekeyAfterTime and RejectAfterTime", code == 400 and "RekeyAfterTime" in e and "RejectAfterTime" in e, (code, r))
    code, r = update("n31", "awg5", awg_params=dict(FULL31))
    check("control: Amnezia's defaults (120 + 7 + 15 ≤ 150) are saved", code == 200, (code, r))
    code, r = update("n31", "awg5", awg_params={**FULL31, "RandomTrailers": "on", "ContentPaddingAddition": "20 - 90"})
    a = ov("n31", "awg5").get("awg_params") or {}
    check("…booleans are stored as 1 and a range in one spelling", a.get("RandomTrailers") == "1"
          and a.get("ContentPaddingAddition") == "20-90", a)

    SECTION[0] = "[6]"
    print("\n[6] a second switch to 3.1 keeps the HeaderProtectionKey")
    put_record("n31", "awg6", {"awg_params": dict(BASE20)})     # its own interface: no section leans on another's result
    sync("n31", dict(BASE20), "awg6")
    update("n31", "awg6", awg_gen="3.1")
    before = (ov("n31", "awg6").get("awg_params") or {}).get("HeaderProtectionKey")
    code, r = update("n31", "awg6", awg_gen="3.1")
    check("the second switch is accepted", code == 200 and bool(before), (code, r, before))
    check("…and the key is the same one", (ov("n31", "awg6").get("awg_params") or {}).get("HeaderProtectionKey") == before,
          (before, (ov("n31", "awg6").get("awg_params") or {}).get("HeaderProtectionKey")))

    SECTION[0] = "[7]"
    print("\n[7] over a PARTIAL record the switch and the 3.1 create store the FULL dict; the restore sends the same S/H")
    put_record("n31", "awg7", {"awg_params": {"Jc": "6"}})     # e.g. an operator's partial interface defaults; node away
    code, r = update("n31", "awg7", awg_gen="3.1")
    a = ov("n31", "awg7").get("awg_params") or {}
    check("switch accepted", code == 200, (code, r))
    check("the record holds every 2.0 key and the 3.1 set", all(k in a for k in list(BASE20) + list(SET31)),
          sorted(set(BASE20) | set(SET31) - set(a)))
    check("…the operator's Jc is kept", a.get("Jc") == "6", a.get("Jc"))
    rr = P.iface_restore_req({**ov("n31", "awg7"), "_lastcfg": {"subnet": "10.60.7.0/24"}}) or {}
    ra = rr.get("awg_params") or {}
    check("the restore request sends the same S1–S4 and H1–H4", all(ra.get(k) == a.get(k) for k in
          ("S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4")) and all(k in ra for k in ("S1", "H1")),
          {k: (ra.get(k), a.get(k)) for k in ("S1", "H1")})
    code, r = req("/api/panel/settings", {"interface_defaults": {"awg_params": {"Jc": "7"}}})
    assert code == 200, (code, r)
    code, r = req("/api/iface/create", {"node": "n31", "iface": "awg7c", "subnet": "10.62.0.0/24", "awg_gen": "3.1"})
    cr = ((nodes()["n31"].get("create") or {}).get("awg7c") or {}).get("awg_params") or {}
    rec = ov("n31", "awg7c").get("awg_params") or {}
    check("3.1 create accepted", code == 200, (code, r))
    check("…the create request carries the full dict, and the record is the same dict",
          all(k in cr for k in list(BASE20) + list(SET31)) and cr == rec, sorted(set(BASE20) | set(SET31) - set(cr)))
    check("…the operator's partial default (Jc 7) is in it", cr.get("Jc") == "7", cr.get("Jc"))
    check("…S1–S4 ≥ 12 and HPK a 32-byte key", s_ok(cr) and len(__import__("base64").b64decode(cr.get("HeaderProtectionKey", ""))) == 32, cr)

    SECTION[0] = "[8]"
    print("\n[8] synced means the whole generation matches")
    put_record("n31", "awg8", {"awg_params": dict(FULL31)})
    sync("n31", dict(FULL31), "awg8")
    code, r = update("n31", "awg8", awg_gen="2.0")
    check("switch back accepted, record without any 3.x key", code == 200 and not any(k in ov("n31", "awg8")["awg_params"] for k in AWG3),
          ov("n31", "awg8").get("awg_params"))
    d = sync("n31", dict(FULL31), "awg8")                       # the node still has the HPK
    check("a leftover HeaderProtectionKey is NOT synced: the 2.0 set is pushed", d.get("awg_params") == BASE20, d)
    check("…marked whole (awg_params_exact), so the node drops the keys it lacks", d.get("awg_params_exact") is True, d)
    check("…and the record is not marked synced", (ov("n31", "awg8").get("_synced") or {}).get("awg_params") != BASE20,
          ov("n31", "awg8").get("_synced"))
    d = sync("n31", dict(BASE20), "awg8")
    check("once the node reports no 3.x key: synced, nothing pushed", "awg_params" not in d and
          (ov("n31", "awg8").get("_synced") or {}).get("awg_params") == BASE20, d)
    d = sync("n31", dict(FULL31), "awg8")                       # a key appears on a CONFIRMED 2.0 interface
    dr = (ov("n31", "awg8").get("_drift") or {}).get("awg_params") or {}
    check("a confirmed 2.0 record meeting an unexpected HPK is drift, not a push", "awg_params" not in d
          and dr.get("HeaderProtectionKey") == HPK, (d, dr))
    code, r = req("/api/iface/adopt", {"node": "n31", "iface": "awg8", "key": "awg_params"})
    check("…and Adopt takes the key into the record", ov("n31", "awg8")["awg_params"].get("HeaderProtectionKey") == HPK,
          ov("n31", "awg8").get("awg_params"))

    SECTION[0] = "[10]"
    print("\n[10] an older node is asked for no switch, and gets no 3.x set by a create or a recreate")
    put_record("nold", "awg10", {"awg_params": dict(FULL31), "_lastcfg": {"subnet": "10.60.10.0/24", "listen_port": 51850}})
    sync("nold", dict(BASE20), "awg10")
    code, r = update("nold", "awg10", awg_gen="2.0")
    check("a switch BACK on an older node → 400 (its agent cannot remove the key; it would read as synced)",
          code == 400 and "does not report its AmneziaWG version" in (r.get("error") or ""), (code, r))
    check("…and the record keeps its 3.1 set", ov("nold", "awg10")["awg_params"].get("HeaderProtectionKey") == HPK)
    put_record("nold", "awg11", {"awg_params": dict(FULL31)})
    code, r = req("/api/iface/create", {"node": "nold", "iface": "awg11", "subnet": "10.60.11.0/24"})
    check("the create door rebuilding a 3.1 record on an older node → 400", code == 400 and "does not report" in (r.get("error") or ""), (code, r))
    put_record("nold", "awg15", {"awg_params": dict(FULL31), "public_key": PUB,     # lost on the node: never reported
                                 "_lastcfg": {"subnet": "10.60.15.0/24", "listen_port": 51855}})
    code, r = req("/api/iface/recreate", {"node": "nold", "iface": "awg15"})
    check("…and so does /api/iface/recreate of a lost 3.1 interface", code == 400 and "does not report" in (r.get("error") or ""), (code, r))
    check("…nothing queued for it", not {"awg11", "awg15"} & set(nodes()["nold"].get("create") or {}), nodes()["nold"].get("create"))
    put_record("nold", "awg12", {"awg_params": dict(BASE20)})
    code, r = req("/api/iface/create", {"node": "nold", "iface": "awg12", "subnet": "10.60.12.0/24"})
    check("control: a 2.0 create door on the older node is as before", code == 200, (code, r))

    SECTION[0] = "[11]"
    print("\n[11] a switch never carries DisableCookies")
    put_record("n31", "awg13", {"awg_params": {**BASE20, "DisableCookies": "on"}})
    sync("n31", {**BASE20, "DisableCookies": "on"}, "awg13")
    code, r = update("n31", "awg13", awg_gen="3.1")
    check("the switch is accepted, and the record holds no DisableCookies", code == 200 and "DisableCookies" not in ov("n31", "awg13")["awg_params"],
          ov("n31", "awg13").get("awg_params"))

    SECTION[0] = "[12]"
    print("\n[12] a 3.x key at 0 / off is unset; an all-zero key is refused")
    put_record("n31", "awg14", {"awg_params": dict(FULL31)})
    code, r = update("n31", "awg14", awg_params={**FULL31, "ContentPaddingAddition": "0", "RekeyTimeout": "0"})
    a = ov("n31", "awg14").get("awg_params") or {}
    check("saved without the zero keys", code == 200 and "ContentPaddingAddition" not in a and "RekeyTimeout" not in a, a)
    code, r = update("n31", "awg14", awg_params={**FULL31, "HeaderProtectionKey": "A" * 43 + "="})
    check("an all-zero HeaderProtectionKey → 400", code == 400 and "HeaderProtectionKey" in (r.get("error") or ""), (code, r))

    SECTION[0] = "[9]"
    print("\n[9] a 2.0 interface: nothing new on the wire")
    put_record("n31", "awg9", {"awg_params": dict(BASE20)})
    d = sync("n31", {**BASE20, "Jc": "3"}, "awg9")
    check("its push is the 2.0 dict with no new field", d.get("awg_params") == BASE20 and "awg_params_exact" not in d, d)
    d = sync("n31", dict(BASE20), "awg9")
    check("…and once synced nothing is sent", "awg_params" not in d, d)
    code, r = update("n31", "awg9", awg_params={**BASE20, "Jc": "8"})
    check("an ordinary 2.0 Edit save still goes through untouched", code == 200 and ov("n31", "awg9")["awg_params"] == {**BASE20, "Jc": "8"},
          ov("n31", "awg9").get("awg_params"))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    _plog = open(log.name).read()
    shutil.rmtree(TMP, ignore_errors=True)

check("no Traceback in the panel log", "Traceback" not in _plog, _plog[-1500:])
print()
if MODE:
    want = PLANTS[MODE][0]
    red = sorted({s for s, _ in FAILS})
    ok = red == [want]
    print(("PERTURB OK — %s went red on %s only" if ok else "PERTURB FAILED — %s: red sections %s, wanted exactly %s")
          % ((MODE, want) if ok else (MODE, red, want)))
    sys.exit(0 if ok else 1)
if FAILS:
    print("FAILED: " + "; ".join("%s %s" % f for f in FAILS)); sys.exit(1)
print("ALL PASS"); sys.exit(0)
