#!/usr/bin/env python3
"""Self-test — what the panel hands the AmneziaWG 3.1 UI (docs/AWG3-PLAN.md §7.7, P3).

Two facts the SPA reads instead of deciding them itself. Driven through a REAL panel process (temp state, scratch port, no
auth; three nodes played by POSTing snapshots; `curl` shimmed so nothing is fetched).

  [1] /api/state `nodes[].awg31_no` — the panel's own refusal of a 3.1 interface on each node, which the create form greys
      its switch with: a node whose module is 2.0 gets the "kernel module is 2.0" sentence with its name and version as
      values, a node that reports no generation gets "update it", a 3.1 node gets null — and each is the SAME perr the
      create refuses with, sentence for sentence
  [2] Settings → Interfaces `interface_defaults.awg_gen` (D-default): "3.1" is stored; a save that does not carry the key (an
      older tab) keeps it; "2.0" removes it — 2.0 is its absence, so a fleet that never picks 3.1 keeps the panel-settings
      file it had; the panel-wide awg_params stay 2.0 whatever the preset says
  [3] a node's snapshot is remote input: one whose `datapath` (or its `gen`) is malformed gets "update it" or a refusal —
      and /api/state keeps answering for every node, since awg31_no runs inside its loop
  [4] per interface where the answer differs: on a node whose kernel module is 2.0, an interface running on a 3.1 userspace
      fallback is judged by that fallback — /api/state says so (`awg31_no_us`) and the switch of it goes through — while a
      kernel interface on the same node stays refused; a node with nothing on the fallback carries no such key

Run: python3 tests/awg3_ui_selftest.py        (0 = pass)
     --perturb <name>   plants one regression in a copy of the panel and expects RED on exactly its sections:
                        refusal [1][3][4] · store20 [2] · keep [2] · fragile [3][4] · us [4]
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANTS = {
    "refusal": ('                        "awg31_no": awg_gen_refusal(snap, c.get("name", nid)),\n',
                '                        "awg31_no": None,\n', ["[1]", "[3]", "[4]"]),
    "us": ('                        **({"awg31_no_us": {i: awg_gen_refusal(snap, c.get("name", nid), i) for i in _awg_datapath(snap)["userspace"]}}\n',
           '                        **({"awg31_no_us": {}}\n', ["[4]"]),
    "store20": ('            if _ag == "3.1":\n                cur["interface_defaults"]["awg_gen"] = "3.1"\n',
                '            if _ag:\n                cur["interface_defaults"]["awg_gen"] = _ag\n', ["[2]"]),
    "keep": ('            _ag = idf.get("awg_gen") if idf.get("awg_gen") in ("2.0", "3.1") else (cur.get("interface_defaults") or {}).get("awg_gen")\n',
             '            _ag = idf.get("awg_gen")\n', ["[2]"]),
    "fragile": ('    return isinstance(_awg_datapath(snap).get("gen"), dict)\n',
                '    return isinstance((((snap if isinstance(snap, dict) else {}).get("datapath") or {}).get("awg") or {}).get("gen"), dict)\n', ["[3]", "[4]"]),   # the poll fails for every node after it
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None
FAILS = []; SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="awg3-ui-")
SERVER = os.path.join(ROOT, "swg-panel-server")
if MODE:
    old, new, _ = PLANTS[MODE]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    SERVER = os.path.join(TMP, "swg-panel-server")
    open(SERVER, "w", encoding="utf-8").write(src.replace(old, new))
    shutil.copy2(os.path.join(ROOT, "VERSION"), os.path.join(TMP, "VERSION"))
    print("== PERTURB %s planted" % MODE)

state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in ("m31", "nix", "old", "bad", "bad2", "fb")}, open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
SHIM = os.path.join(TMP, "shim"); os.makedirs(SHIM)
open(os.path.join(SHIM, "curl"), "w").write("#!/bin/sh\nexit 6\n"); os.chmod(os.path.join(SHIM, "curl"), 0o755)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, SERVER], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "PATH": SHIM + os.pathsep + os.environ.get("PATH", ""), "SWG_PANEL_FLEET": fleet,
                             "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT),
                             "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})
def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
try:
    for _ in range(200):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % PORT, timeout=2); break
        except Exception:
            time.sleep(0.1)
    tok = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("m31", "nix", "old", "bad", "bad2", "fb")}
    GEN = {"m31": {"module": "3.1", "fallback": "3.1", "tools": "3.1"}, "nix": {"module": "2.0", "fallback": "2.0", "tools": "2.0"}}
    for n in ("m31", "nix", "old"):
        snap = {"hostname": n, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
                "datapath": {"awg": {"needed": True, "ok": True}}}
        if n in GEN:
            snap["datapath"]["awg"]["gen"] = GEN[n]
        req("/api/node/sync", {"snapshot": snap}, tok[n])
    by = {n["id"]: n for n in (req("/api/state")[1].get("data") or {}).get("nodes") or []}

    SECTION[0] = "[1]"; print("[1] /api/state awg31_no — the panel's own refusal, per node")
    nix, old, m31 = (by.get(n, {}).get("awg31_no") for n in ("nix", "old", "m31"))
    check("a 2.0-module node: the kernel-module sentence, name + version as values",
          isinstance(nix, dict) and nix.get("error_key") == "{v1}: its AmneziaWG kernel module is {v2} — an AmneziaWG 3.1 interface needs 3.1"
          and nix.get("error_vars") == {"v1": "nix", "v2": "2.0"}, nix)
    check("a node that reports no generation: update it", isinstance(old, dict)
          and old.get("error_key") == "{v1}: this node does not report its AmneziaWG version — update it", old)
    check("a 3.1 node: null (the switch is offered)", "awg31_no" in by.get("m31", {}) and m31 is None, by.get("m31", {}).get("awg31_no", "absent"))
    for n, v in (("nix", nix), ("old", old)):
        c, r = req("/api/iface/create", {"node": n, "iface": "awg7", "protocol": "awg", "subnet": "10.77.%d.0/24" % len(n),
                                         "listen_port": 51877, "awg_gen": "3.1"})
        check("%s: the create refuses with the same sentence (%d)" % (n, c), c == 400 and isinstance(v, dict)
              and r.get("error_key") == v.get("error_key") and r.get("error_vars") == v.get("error_vars"), r)

    SECTION[0] = "[2]"; print("[2] interface_defaults.awg_gen — the create form's preset, stored only as 3.1")
    PS = os.path.join(state, "panel-settings.json")
    idf = lambda: (json.load(open(PS)) if os.path.exists(PS) else {}).get("interface_defaults") or {}
    base = {"dns": ["1.1.1.1"], "mtu": 1280, "keepalive": 25, "awg_params": {}, "reach": "user"}
    req("/api/panel/settings", {"interface_defaults": {**base, "awg_gen": "2.0"}})
    check("a 2.0 save stores no key (2.0 is its absence)", os.path.exists(PS) and "awg_gen" not in idf(), idf())
    req("/api/panel/settings", {"interface_defaults": {**base, "awg_gen": "3.1"}})
    check("a 3.1 save stores it", idf().get("awg_gen") == "3.1", idf())
    req("/api/panel/settings", {"interface_defaults": dict(base)})
    check("a save that does not carry it (an older tab) keeps it", idf().get("awg_gen") == "3.1", idf())
    check("the panel-wide awg_params stay 2.0 — the preset is not a parameter", idf().get("awg_params") == {}, idf())
    st = ((req("/api/state")[1].get("data") or {}).get("panel_settings") or {}).get("interface_defaults") or {}
    check("/api/state serves it to the create form", st.get("awg_gen") == "3.1", st)
    req("/api/panel/settings", {"interface_defaults": {**base, "awg_gen": "4.0"}})
    check("an unknown value is no value — the stored one stays", idf().get("awg_gen") == "3.1", idf())
    req("/api/panel/settings", {"interface_defaults": {**base, "awg_gen": "2.0"}})
    check("back to 2.0 removes it", "awg_gen" not in idf(), idf())

    SECTION[0] = "[3]"; print("[3] a malformed report never fails the poll")
    for n, dp in (("bad", "not-a-dict"), ("bad2", {"awg": {"gen": {"module": ["3.1"], "tools": 31}}})):
        c, r = req("/api/node/sync", {"snapshot": {"hostname": n, "generated_at": int(time.time()), "noded_version": "t",
                                                    "interfaces": {}, "datapath": dp}}, tok[n])
        check("%s: its sync is answered (%d)" % (n, c), c == 200, r)
    c, st = req("/api/state")
    by = {n["id"]: n for n in (st.get("data") or {}).get("nodes") or []}
    check("/api/state still answers 200 (%d)" % c, c == 200 and len(by) == 6, (c, str(st)[:200]))
    check("a datapath that is not a dict: update it", ((by.get("bad") or {}).get("awg31_no") or {}).get("error_key")
          == "{v1}: this node does not report its AmneziaWG version — update it", (by.get("bad") or {}).get("awg31_no"))
    check("versions that are not strings count as none — refused, not a crash", isinstance((by.get("bad2") or {}).get("awg31_no"), dict),
          (by.get("bad2") or {}).get("awg31_no"))
    check("…and the healthy nodes keep their answers", (by.get("m31") or {}).get("awg31_no", "absent") is None
          and isinstance((by.get("nix") or {}).get("awg31_no"), dict))

    SECTION[0] = "[4]"; print("[4] an interface on the userspace fallback is judged by it, not by the module")
    S20 = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33",
           "H1": "103509605-103509620", "H2": "1694692368-1694692383", "H3": "2553282719-2553282734", "H4": "3170237912-3170237927"}
    def ifc(port, net):
        return {"peers": [], "meta": {"public_key": "PUB%d" % port, "listen_port": port, "mtu": 1280, "subnet": net + ".0/24",
                                      "address": net + ".1/24", "awg_params": dict(S20), "tool": "awg", "dns": []}}
    c, r = req("/api/node/sync", {"snapshot": {"hostname": "fb", "generated_at": int(time.time()), "noded_version": "t",
                                               "interfaces": {"awg5": ifc(51825, "10.55.0"), "awg6": ifc(51826, "10.56.0")},
                                               "datapath": {"awg": {"needed": True, "ok": True, "userspace": ["awg5"],
                                                                    "gen": {"module": "2.0", "fallback": "3.1", "tools": "3.1"}}}}}, tok["fb"])
    fb = {n["id"]: n for n in (req("/api/state")[1].get("data") or {}).get("nodes") or []}.get("fb") or {}
    check("the node's own answer is the module's (a new interface gets the module)", ((fb.get("awg31_no") or {}).get("error_key") or "")
          .startswith("{v1}: its AmneziaWG kernel module is"), fb.get("awg31_no"))
    check("awg5 on the 3.1 fallback: offered (null)", "awg5" in (fb.get("awg31_no_us") or {}) and fb["awg31_no_us"]["awg5"] is None, fb.get("awg31_no_us"))
    check("awg6 on the kernel is not in the per-interface map", "awg6" not in (fb.get("awg31_no_us") or {}), fb.get("awg31_no_us"))
    c5, r5 = req("/api/iface/update", {"node": "fb", "iface": "awg5", "awg_gen": "3.1"})
    check("…and the panel switches awg5 (%d)" % c5, c5 == 200, r5)
    c6, r6 = req("/api/iface/update", {"node": "fb", "iface": "awg6", "awg_gen": "3.1"})
    check("…while awg6 is refused for the module (%d)" % c6, c6 == 400 and "kernel module" in str(r6.get("error_key")), r6)
    check("a node with nothing on the fallback carries no per-interface map", all("awg31_no_us" not in (n or {}) for k, n in by.items() if k != "fb"))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
lg = open(log.name).read()
check("no Traceback in the panel log", "Traceback" not in lg, lg[-600:])
shutil.rmtree(TMP, ignore_errors=True)
print()
if MODE:
    want = set(PLANTS[MODE][2]); got = {s for s, _ in FAILS}
    ok = got == want
    print(("PERTURB %s OK — red on exactly %s" % (MODE, sorted(want))) if ok else "PERTURB %s WRONG — red on %s, wanted %s" % (MODE, sorted(got), sorted(want)))
    sys.exit(0 if ok else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
