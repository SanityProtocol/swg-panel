#!/usr/bin/env python3
"""Self-test — csqtt version LINES, the panel's half (docs/CSQTT-LINES-PLAN.md §4.3, gates G1 + P2).

A REAL panel process (temp state, scratch port, no auth) started with SWG_CSQTT_STANDIN="2.5=2.1.9-3" — the stand-in
line made of a build that is already published — and the node's side played by POSTing snapshots to /api/node/sync.
`nnew` advertises `csqtt_lines`; `nold` is an older noded that does not.

  [1] G1         an old node gets today's reply for a 2.1 server (no `line`, 2.1's build) and NO `ver` at all for a
                 server whose record says another line — an old noded would put that build under every csqtt server
  [2] reply      a capable node gets each server's line and that line's build
  [3] refuse     2.5 on a node that cannot run it is a 400 naming the node; an unknown line is a 400; 2.1 is the
                 absent value in the record; a switch is logged
  [4] publish    csqtt_cfg carries `line` (or the next save from the SPA posts it back as 2.1) and /api/state lists
                 the lines on offer
  [5] holds      versions + rollback are per (node, line): 2.5's picker lists 2.5's builds, a 2.1 build is refused
                 there, the hold lands on fork:csqtt@2.5 and moves only the 2.5 server's `ver`
  [6] updates    a 2.5 server is its own update unit: behind 2.5's latest it is a row {fork: csqtt, line: 2.5}; a
                 2.1 server on 2.1's newest is not behind (and a 2.5 server is never "behind" 2.1's latest)
  [7] prune      every line's current build and a per-line hold are in the mirror's needed-set
  [8] mirror     a server the node runs with no record is recorded with the line it runs (or the next reply
                 would ask the node to switch it to 2.1)
  [9] default    without SWG_CSQTT_STANDIN there is one line and /api/state offers one; a stand-in never replaces a
                 real line
  [10] unoffered a server recorded on a line this panel does not offer (the stand-in unset, a panel rolled back) gets
                 no line and no build — the node keeps what runs — and the mirror records such a line as it runs
  code review (2026-10-08):
  [11] running   during a pending/failed switch (record 2.5, the node runs 2.1) the version endpoints act on the line
                 the server RUNS — the one its update row and Version row show — and the reply names that line's
                 build as `cur_ver` so it keeps getting updates
  [12] offline   a hold for a server on a line this panel does not offer is refused, saying why (no build of that
                 line is listed here); no 2.1 hold results

Run: python3 tests/csqtt_lines_panel_selftest.py   (0 = pass)
     --perturb <name>  plants one regression and expects RED on its section:
                       g1 [1] · refuse [3] · publish [4] · holdkey [5] · split [6] · needed [7] · mirror [8] ·
                       override [9] · unoffered [10] · runline / runline-get / curver [11] · refuseoff [12]
"""
import importlib.machinery, importlib.util, json, os, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")

PLANTS = {
    "g1": ("[1]", "        elif _line != CSQTT_DEFAULT_LINE:\n            _cver = \"\"", "        elif False:\n            _cver = \"\""),
    "refuse": ("[3]", "                if _ln not in (_lsnap.get(\"csqtt_lines\") or []):", "                if False:"),
    "publish": ("[4]", "\"dns_orig\", \"bind_ip\", \"line\") if k in ov}", "\"dns_orig\", \"bind_ip\") if k in ov}"),
    "holdkey": (("[5]", "[11]"), "    return \"fork:csqtt\" if line == CSQTT_DEFAULT_LINE else \"fork:csqtt@\" + line",
                "    return \"fork:csqtt\""),
    "split": ("[6]", "                if _cl and _cl != CSQTT_DEFAULT_LINE:\n                    _cf += \"@\" + _cl\n",
              "                pass\n"),
    "needed": ("[7]", "    for _cl in CSQTT_LINES:                   # every line's current build",
               "    for _cl in [CSQTT_DEFAULT_LINE]:          # every line's current build"),
    "override": ("[9]", "and line not in CSQTT_LINES and builds:", "and builds:"),
    "unoffered": ("[10]", "        if _line not in CSQTT_LINES:\n", "        if False:\n"),
    "runline-get": ("[11]", "        _vl = (_csqtt_run_line(((deps.get(\"node_snaps\") or {}).get(nid)), _qi, _vi) if _vi",
                    "        _vl = (_csqtt_line_of(_vi) if _vi"),
    "runline": (("[11]", "[12]"), "        _vl = (_csqtt_run_line(((deps.get(\"node_snaps\") or {}).get(nid)), iface, ((nodes[nid].get(\"csqtt\")) or {}).get(iface))",
                "        _vl = (_csqtt_line_of(((nodes[nid].get(\"csqtt\")) or {}).get(iface))"),
    "curver": ("[11]", "            if _run and _run != _line and _run in CSQTT_LINES:", "            if False:"),
    "refuseoff": ("[12]", "        if _vl not in CSQTT_LINES:\n            # a server on a line", "        if False:\n            # a server on a line"),
    "mirror": (("[8]", "[10]"), "                    _inst[\"line\"] = _rep[\"line\"]", "                    pass"),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else ""
SECTION = [""]
FAILS = []
def section(s):
    SECTION[0] = s; print(s, flush=True)
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="csqtt-lines-panel-")
server = SERVER
if MODE:
    _sec, old, new = PLANTS[MODE]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    server = os.path.join(TMP, "swg-panel-server")
    open(server, "w", encoding="utf-8").write(src.replace(old, new))

def load(name, standin):
    if standin:
        os.environ["SWG_CSQTT_STANDIN"] = standin
    else:
        os.environ.pop("SWG_CSQTT_STANDIN", None)
    ld = importlib.machinery.SourceFileLoader(name, server)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    return m
P = load("swgpanel_lines", "2.5=2.1.9-3")
P1 = load("swgpanel_lines_off", "")

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

state = os.path.join(TMP, "state"); os.makedirs(state); stats = os.path.join(TMP, "stats"); os.makedirs(stats)
NODES = os.path.join(state, "nodes.json")
C1 = {"listen": "0.0.0.0:46000", "tun_addr": "10.66.67.1/24", "max_passwords": 500}
json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {},
               "csqtt": {"csqtt1": dict(C1, tun_addr="10.66.%d.1/24" % (67 + i))}} for i, n in enumerate(("nnew", "nold"))},
          open(NODES, "w"))
open(os.path.join(state, "users.json"), "w").write("{}\n")
fleet = os.path.join(TMP, "fleet.json")
json.dump({"nodes_path": NODES, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
PORT = free_port()
log = open(os.path.join(TMP, "panel.log"), "w+")
proc = subprocess.Popen([sys.executable, server], stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, "SWG_CSQTT_STANDIN": "2.5=2.1.9-3", "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT,
                             "SWG_PANEL_HOST": "127.0.0.1", "SWG_PANEL_PORT": str(PORT), "SWG_PANEL_AUTH": "",
                             "SWG_PANEL_TLS_CERT": "", "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0"})

def req(path, data=None, token=None):
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                               data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read(); code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read(); code = e.code
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
    TOK = {n: req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("nnew", "nold")}

    def nodes():
        return json.load(open(NODES))
    def put_csqtt(nid, iface, rec):
        n = nodes(); n[nid].setdefault("csqtt", {})[iface] = rec
        with open(NODES + ".tmp", "w") as f:
            json.dump(n, f)
        os.replace(NODES + ".tmp", NODES)
    def snap(nid, rows=None):
        s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
             "csqtt": rows if rows is not None else [{"iface": i, "kind": "csqtt", "fork": "csqtt", "active": "active",
                                                       "version": "2.1.9-4", "line": "2.1", "max_passwords": 500, "params": ""}
                                                      for i in (nodes()[nid].get("csqtt") or {})]}
        if nid == "nnew":
            s["csqtt_lines"] = ["2.1", "2.5"]
        else:
            for r in s["csqtt"]:
                r.pop("line", None)
        return s
    def sync(nid, rows=None):
        code, r = req("/api/node/sync", {"snapshot": snap(nid, rows)}, TOK[nid])
        assert code == 200, (code, r)
        return r.get("csqtt") or {}

    section("[1] G1 — an old node")
    r = sync("nold")
    c1 = r.get("csqtt1") or {}
    check("a 2.1 server: no `line` in the reply", "line" not in c1, c1)
    check("a 2.1 server: 2.1's current build, as today", c1.get("ver") == "2.1.9-4", c1.get("ver"))
    put_csqtt("nold", "csqtt2", dict(C1, tun_addr="10.66.90.1/24", listen="0.0.0.0:46010", line="2.5"))
    c2 = (sync("nold").get("csqtt2") or {})
    check("a server recorded on 2.5: no `ver` at all (nothing for the old noded to swap)", "ver" not in c2, c2)
    check("…and no `line`", "line" not in c2, c2)

    section("[2] a capable node")
    c1 = sync("nnew").get("csqtt1") or {}
    check("a 2.1 server gets line 2.1 and 2.1's build", c1.get("line") == "2.1" and c1.get("ver") == "2.1.9-4", c1)

    section("[3] switching from the panel")
    code, r = req("/api/csqtt/set", {"node": "nold", "iface": "csqtt1", "line": "2.5"})
    check("2.5 on a node that cannot run it is refused", code == 400 and r.get("code") == "node_too_old", (code, r))
    code, r = req("/api/csqtt/set", {"node": "nnew", "iface": "csqtt1", "line": "9.9"})
    check("a line the panel does not offer is refused", code == 400, (code, r))
    code, r = req("/api/csqtt/set", {"node": "nnew", "iface": "csqtt1", "line": "2.5"})
    check("2.5 on a capable node is accepted", code == 200, (code, r))
    check("the record says line 2.5", (nodes()["nnew"]["csqtt"]["csqtt1"]).get("line") == "2.5", nodes()["nnew"]["csqtt"]["csqtt1"])
    c1 = sync("nnew").get("csqtt1") or {}
    check("the next reply asks for line 2.5 with 2.5's build", c1.get("line") == "2.5" and c1.get("ver") == "2.1.9-3", c1)
    code, ev = req("/api/events?limit=50")
    check("the switch is in the activity log", "Switching a csqtt server's version" in json.dumps(ev), str(ev)[:200])

    section("[4] what the SPA reads")
    code, st = req("/api/state")
    d = st.get("data") or st
    nn = next((n for n in (d.get("nodes") or []) if n.get("id") == "nnew"), {})
    check("csqtt_cfg publishes the line", ((nn.get("csqtt_cfg") or {}).get("csqtt1") or {}).get("line") == "2.5", nn.get("csqtt_cfg"))
    check("/api/state offers 2.1 and 2.5", d.get("csqtt_lines") == ["2.1", "2.5"], d.get("csqtt_lines"))

    section("[5] versions and holds per line")
    put_csqtt("nnew", "csqtt2", dict(C1, tun_addr="10.66.91.1/24", listen="0.0.0.0:46020"))
    sync("nnew", [{"iface": "csqtt1", "kind": "csqtt", "fork": "csqtt", "line": "2.5", "version": "2.1.9-3", "max_passwords": 500, "params": ""},
                  {"iface": "csqtt2", "kind": "csqtt", "fork": "csqtt", "line": "2.1", "version": "2.1.9-4", "max_passwords": 500, "params": ""}])   # the switch landed
    code, v = req("/api/csqtt/versions?node=nnew&iface=csqtt1")
    vd = v.get("data") or {}
    check("2.5's picker lists 2.5's builds", vd.get("line") == "2.5" and vd.get("versions") == ["2.1.9-3"], vd)
    code, v = req("/api/csqtt/versions?node=nnew&iface=csqtt2")
    check("2.1's picker lists 2.1's builds", (v.get("data") or {}).get("versions", [None])[0] == "2.1.9-4", v)
    code, r = req("/api/csqtt/version", {"node": "nnew", "iface": "csqtt1", "ver": "2.1.9-4"})
    check("a 2.1 build is not a 2.5 rollback target", code == 400, (code, r))
    code, r = req("/api/csqtt/version", {"node": "nnew", "iface": "csqtt1", "ver": "2.1.9-3"})
    holds = json.load(open(os.path.join(state, "turn-holds.json"))) if os.path.exists(os.path.join(state, "turn-holds.json")) else {}
    check("the hold lands on fork:csqtt@2.5", code == 200 and "nnew|fork:csqtt@2.5" in holds and "nnew|fork:csqtt" not in holds, (code, holds))
    rr = sync("nnew", [{"iface": "csqtt1", "kind": "csqtt", "fork": "csqtt", "line": "2.5", "version": "2.1.9-3", "max_passwords": 500, "params": ""},
                       {"iface": "csqtt2", "kind": "csqtt", "fork": "csqtt", "line": "2.1", "version": "2.1.9-4", "max_passwords": 500, "params": ""}])
    check("the 2.1 server's ver is untouched by 2.5's hold", (rr.get("csqtt2") or {}).get("ver") == "2.1.9-4", rr.get("csqtt2"))
    check("state's turn_holds names the 2.5 hold apart", ((d2 := (req("/api/state")[1].get("data") or {})).get("turn_holds") or {}).get("nnew", {}).get("csqtt@2.5") == "2.1.9-3", d2.get("turn_holds"))

    section("[6] updates per line")
    deps = {"node_snaps": {"n": {"csqtt": [
        {"iface": "a", "fork": "csqtt", "line": "2.5", "version": "2.1.9-2"},
        {"iface": "b", "fork": "csqtt", "line": "2.1", "version": "2.1.9-4"},
        {"iface": "c", "fork": "csqtt", "version": "2.1.9-4"}]}}}
    P.TURN_HOLDS_PATH = os.path.join(TMP, "holds-mod.json")
    P._check_turn_latest(deps)
    rows = P.turn_updates_view(deps)
    check("one row: the 2.5 server behind 2.5's latest", [(x.get("fork"), x.get("line"), x.get("ids"), x.get("latest")) for x in rows] == [("csqtt", "2.5", ["a"], "2.1.9-3")], rows)
    deps["node_snaps"]["n"]["csqtt"][0]["version"] = "2.1.9-3"
    P._check_turn_latest(deps)
    check("a 2.5 server on 2.5's newest is not behind 2.1's latest", P.turn_updates_view(deps) == [], P.turn_updates_view(deps))

    section("[7] the mirror's needed-set")
    P.Handler.deps = {"stats_dir": stats}
    P.CSQTT_LINES["2.5"] = [("2.5.0-1", "csqtt-2.5.0-1")]
    json.dump({"x|fork:csqtt@2.5": {"tag": "2.5.0-0"}}, open(P.TURN_HOLDS_PATH, "w"))
    need = (P._turn_bins_needed() or {}).get(P.CSQTT_MIRROR_OWNER) or set()
    check("2.5's current build is needed", "2.5.0-1" in need, need)
    check("2.1's current build is needed", "2.1.9-4" in need, need)
    check("a 2.5 hold is needed", "2.5.0-0" in need, need)
    P.CSQTT_LINES["2.5"] = [("2.1.9-3", "csqtt-2.1.9-3")]

    section("[8] the T-18 mirror records the running line")
    rows = [{"iface": "csqtt1", "kind": "csqtt", "fork": "csqtt", "line": "2.5", "version": "2.1.9-3", "max_passwords": 500, "params": ""},
            {"iface": "csqtt2", "kind": "csqtt", "fork": "csqtt", "line": "2.1", "version": "2.1.9-4", "max_passwords": 500, "params": ""},
            {"iface": "csqtt7", "kind": "csqtt", "fork": "csqtt", "line": "2.5", "version": "2.1.9-3", "listen": "0.0.0.0:46070",
             "tun_addr": "10.66.97.1/24", "max_passwords": 500, "params": "", "passwords": {}}]
    rr = sync("nnew", rows)
    rec7 = (nodes()["nnew"].get("csqtt") or {}).get("csqtt7") or {}
    check("the mirrored record says line 2.5", rec7.get("line") == "2.5", rec7)
    check("…so the reply does not ask the node to switch it", (rr.get("csqtt7") or {}).get("line") in (None, "2.5") and
          ((sync("nnew", rows).get("csqtt7") or {}).get("line") == "2.5"), rr.get("csqtt7"))

    section("[9] the default: no stand-in")
    check("one line on offer", list(P1.CSQTT_LINES) == ["2.1"], list(P1.CSQTT_LINES))
    check("a stand-in naming an unpublished build adds nothing", (P1._csqtt_standin("2.5=9.9.9") or True) and list(P1.CSQTT_LINES) == ["2.1"])
    check("a stand-in cannot replace 2.1", (P1._csqtt_standin("2.1=2.0.1") or True) and P1.CSQTT_LINES["2.1"][0][0] == "2.1.9-4")
    P1.CSQTT_LINES["2.5"] = [("2.5.0-1", "csqtt-2.5.0-1")]
    P1._csqtt_standin("2.5=2.1.9-3")
    check("a stand-in cannot replace a released 2.5", P1.CSQTT_LINES["2.5"] == [("2.5.0-1", "csqtt-2.5.0-1")], P1.CSQTT_LINES["2.5"])
    del P1.CSQTT_LINES["2.5"]

    section("[10] a line this panel does not offer")
    put_csqtt("nnew", "csqtt8", dict(C1, tun_addr="10.66.98.1/24", listen="0.0.0.0:46080", line="3.0"))
    c8 = sync("nnew", rows + [{"iface": "csqtt8", "kind": "csqtt", "fork": "csqtt", "line": "3.0", "version": "3.0.0-1", "max_passwords": 500, "params": ""}]).get("csqtt8") or {}
    check("no line in the reply (the node keeps what runs)", "line" not in c8, c8)
    check("no build in the reply", "ver" not in c8, c8)
    rows9 = rows + [{"iface": "csqtt9", "kind": "csqtt", "fork": "csqtt", "line": "3.0", "version": "3.0.0-1", "listen": "0.0.0.0:46090",
                     "tun_addr": "10.66.99.1/24", "max_passwords": 500, "params": "", "passwords": {}}]
    sync("nnew", rows9)
    check("the mirror records a line it does not offer as it runs", ((nodes()["nnew"].get("csqtt") or {}).get("csqtt9") or {}).get("line") == "3.0",
          (nodes()["nnew"].get("csqtt") or {}).get("csqtt9"))
    section("[11] the line a server runs, during a pending switch")
    put_csqtt("nnew", "csqtt5", dict(C1, tun_addr="10.66.95.1/24", listen="0.0.0.0:46050", line="2.5"))
    rows11 = rows + [{"iface": "csqtt5", "kind": "csqtt", "fork": "csqtt", "line": "2.1", "version": "2.1.9-4", "max_passwords": 500, "params": "",
                      "line_failed": {"line": "2.5", "ver": "2.1.9-3", "why": "x"}}]
    c5 = sync("nnew", rows11).get("csqtt5") or {}
    check("the reply still asks for 2.5 with 2.5's build", c5.get("line") == "2.5" and c5.get("ver") == "2.1.9-3", c5)
    check("…and names the build of the 2.1 it runs as cur_ver", c5.get("cur_ver") == "2.1.9-4", c5)
    code, v = req("/api/csqtt/versions?node=nnew&iface=csqtt5")
    check("its rollback picker is 2.1's (what runs)", (v.get("data") or {}).get("line") == "2.1", v)
    code, r = req("/api/csqtt/version", {"node": "nnew", "iface": "csqtt2", "ver": "2.1.9-3"})   # a 2.1 hold on this node
    check("(setup) a 2.1 hold is set on the node", code == 200 and "nnew|fork:csqtt" in json.load(open(os.path.join(state, "turn-holds.json"))), (code, r))
    code, r = req("/api/csqtt/version", {"node": "nnew", "iface": "csqtt5", "ver": ""})     # Update from its (2.1) row
    holds = json.load(open(os.path.join(state, "turn-holds.json")))
    check("Update from its row releases the 2.1 hold", code == 200 and "nnew|fork:csqtt" not in holds, (code, holds))
    check("…and leaves the 2.5 hold alone", "nnew|fork:csqtt@2.5" in holds, holds)

    section("[12] a hold for a line this panel does not offer")
    code, r = req("/api/csqtt/version", {"node": "nnew", "iface": "csqtt8", "ver": "2.1.9-3"})
    check("refused", code == 400 and "isn't a version" in json.dumps(r), (code, r))
    holds = json.load(open(os.path.join(state, "turn-holds.json")))
    check("…and no 2.1 hold was set by it", "nnew|fork:csqtt" not in holds, holds)
finally:
    proc.terminate()
    try: proc.wait(5)
    except Exception: proc.kill()
    shutil.rmtree(TMP, ignore_errors=True)

if MODE:
    secs = PLANTS[MODE][0] if isinstance(PLANTS[MODE][0], tuple) else (PLANTS[MODE][0],)
    hit = [n for s, n in FAILS if s.startswith(secs)]
    stray = sorted({s.split(" ")[0] for s, n in FAILS if not s.startswith(secs)})
    print("\nperturb %s: %s" % (MODE, ("NOT caught by " + "/".join(secs)) if not hit
          else ("ALSO red outside its section(s): " + ", ".join(stray)) if stray else ("RED on " + "/".join(secs) + " as expected")))
    sys.exit(0 if hit and not stray else 1)
print("\n" + ("ALL PASS" if not FAILS else "%d FAIL: %s" % (len(FAILS), FAILS)))
sys.exit(1 if FAILS else 0)
