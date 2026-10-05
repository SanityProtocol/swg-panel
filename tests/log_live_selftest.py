#!/usr/bin/env python3
"""Self-test for LOGS-PLAN P2 — the live viewer: the request leg, POST /api/node/logs, the lease, the request store, the
reader the node and the panel both run (docs/LOGS-PLAN.md §3, §4, §23).

  [1] The wire, against real panels: an idle fleet's sync reply is byte-identical to the build before the viewer (03add7a)
      — every key, every value, except those two instances of the OLD build disagree on themselves; a request carries
      `logs` only to the nodes it names, and only while it lives.
  [2] POST /api/node/logs: gzip lines reach the viewer; the request's key admits one node into one request (a wrong key
      403, a gone request 404 — the node stops); never the node token (its check parses the whole node store), never
      api(); a gzip bomb and an oversized body are refused.
  [3] The store: the viewer's poll renews the lease, a lapsed one is gone (404, for the viewer and the node); at most 4,
      a 5th refused (not evicting), a replace frees its slot; 5 000 lines kept; the flood cap and the post interval
      scale with the request's size; a skewed node clock is measured; each box's state (old node, offline, no answer,
      waiting, ok); the states block only when it changed.
  [4] The reader (one block, byte-identical in swg-noded and swg-panel-server): a renamed file loses and repeats nothing,
      a copy-truncated one is read again, a cursor resumes (same inode, renamed to .1) or says "!gap"; the flood cap
      skips and says how many; the backfill is the last 200 per source; journal lines are filed by unit / identifier /
      prefix / transport; journalctl's matches are OR-ed; a cursor journalctl refuses → afresh with "!gap", and a dying
      journalctl is not respawned in a loop; a container's stream (Engine API frames) resumes after its last line.
  [5] The node: one reader thread per request, never the sync loop's time; a reader the reply no longer names stops;
      the first post carries each source's state even with no lines; a 404 stops it; the lease stops it with no reply;
      the source plan — units / files / containers, Off, docker's unavailable sources, the panel's sources skipped;
      the log POST is gzip.
  [6] docker: swg-sni's lines reach noded's log file through the pump, at their own priority.
  [7] The panel reads its own journal: the drop-in (installer, update.sh in the upgrade and the heal, uninstall), the
      NixOS unit's group, the docker entrypoint's acme lines; the panel's own plan (bare metal namespace, NixOS main
      journal, docker file, no access yet).

Run: python3 tests/log_live_selftest.py   (0 = pass)
  --plant <x>  plant one defect and expect RED on its own check (exit 0 when caught):
     idleparse    with nothing open, a log post's body is still unpacked and parsed (plan §32 #4)
     replyalways  an idle reply carries `logs`              replyall     a request reaches nodes it does not name
     nodetoken    the log POST checks the node token        nokey        any key is accepted
     bomb         the gzip body is unpacked without a limit nolease      the viewer's poll does not renew the lease
     noexpire     a lapsed request lives on                 evict        a 5th viewer evicts the oldest
     bufgrow      the line buffer has no bound              capflat      the flood cap does not scale with the nodes
     noskew       a node's clock offset is not measured     nodeh        the states block is sent on every poll
     blockdrift   the two copies of the reader differ       renamelose   a renamed file's last lines are lost
     truncstuck   a copy-truncated file is never read again nogap        an unusable resume point says nothing
     floodfree    the flood cap is not applied              andjournal   journalctl's matches are AND-ed
     respawn      a dying journalctl is respawned at once   sniunit      swg-sni's lines are filed under noded
     nostop       a reader the reply drops keeps running    nofirst      no first post without lines
     offread      at Off the namespace's sources are read   dockeriface  docker offers the interfaces' lines
     syncloop     the reader runs in the sync loop          pumpdrop     docker: swg-sni's lines miss noded's file
     nojournal    update.sh never gives the panel its journal
     meshiface    a mesh link's lines are filed as an interface's
     ifacemesh    `iface:*` reads the mesh links too (and `mesh:*` the client interfaces)
     noselect     the panel's copy of the reader misses a module it uses (it ran only in swg-noded's copy)
     pendcount    lines dropped while the panel is away lose an earlier marker's count
     firstspin    a failing first post is retried every half second, not every interval
     nochunk      a backlog goes in one post, over the panel's limits
     panelforever the panel's own reader runs on with no viewer and no node syncing
     strkey       a key that is not ASCII crashes the log POST
     deepjson     a deeply nested body drops the connection (RecursionError) instead of a 400
     curstale     a resume point too big to keep leaves the stale one in place
     backfillcut  a slow (cold) journal's backfill tail goes through the flood cap and reads as skipped
"""
import collections, gzip, importlib.machinery, importlib.util, io, json, os, re, socket, subprocess, sys, tempfile
import threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROG = {k: os.path.join(ROOT, f) for k, f in (("noded", "swg-noded"), ("panel", "swg-panel-server"), ("update", "update.sh"),
                                              ("common", "lib/common.sh"), ("install", "install-host.sh"),
                                              ("uninstall", "uninstall.sh"), ("nix", "nix/modules/panel.nix"),
                                              ("entry", "docker/entrypoint.sh"))}
REF = "03add7a"                                  # the last build before the viewer: the byte-identical reference
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
FAILS = []
TMP = tempfile.mkdtemp(prefix="loglive-")
os.environ["SWG_LOG_LEVEL_FILE"] = os.path.join(TMP, "none", "log-level")


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""),
          flush=True)
    if not cond:
        FAILS.append(name)


PLANTS = {   # (program, anchor, replacement)
    "replyalways": ("panel", '''                                **({"logs": _live} if _live else {}),''',
                    '''                                "logs": _live or [],'''),
    "replyall": ("panel", '''            if nid in rec["nodeset"]:\n                rec["sent"].setdefault(nid, now)''',
                 '''            if True:\n                rec["sent"].setdefault(nid, now)'''),
    "idleparse": ("panel", '''        if not _LIVE_REQS and not _RANGE_REQS:          # nothing open''',
                  '''        if False:          # nothing open'''),
    "nodetoken": ("panel", '''        n = self._body_len(cap=LIVE_POST_MAX)\n        if n is None:\n            return\n''',
                  '''        n = self._body_len(cap=LIVE_POST_MAX)\n        if n is None:\n            return\n        self._node_token()\n'''),
    "nokey": ("panel", '''        if (nid == LIVE_PANEL or nid not in rec["nodeset"]\n                or not hmac.compare_digest(key.encode("utf-8", "replace"), _live_key(rec, nid).encode())):''',
              '''        if (nid == LIVE_PANEL or nid not in rec["nodeset"]):'''),
    "bomb": ("panel", '''                raw = d.decompress(raw, LIVE_POST_RAW_MAX)''', '''                raw = d.decompress(raw)'''),
    "nolease": ("panel", '''        rec["lease"] = now + LIVE_LEASE\n        buf, seq = rec["buf"], rec["seq"]''',
                '''        buf, seq = rec["buf"], rec["seq"]'''),
    "noexpire": ("panel", '''    for rid in [k for k, r in _LIVE_REQS.items() if r["lease"] < now]:''',
                 '''    for rid in [k for k, r in _LIVE_REQS.items() if False]:'''),
    "evict": ("panel", '''        if len(_LIVE_REQS) >= LIVE_REQ_MAX:\n            return 429,''',
              '''        if len(_LIVE_REQS) >= LIVE_REQ_MAX:\n            _LIVE_REQS.pop(next(iter(_LIVE_REQS)))["stop"].set()\n        if False:\n            return 429,'''),
    "bufgrow": ("panel", '''"buf": collections.deque(maxlen=LIVE_BUF)''', '''"buf": collections.deque()'''),
    "capflat": ("panel", '''    return min(200, max(5, LIVE_RATE // max(1, n)))''', '''    return 200'''),
    "noskew": ("panel", '''            rec["off"][nid] = int(round(off)) if abs(off) >= LIVE_SKEW_S else 0''', '''            rec["off"][nid] = 0'''),
    "nodeh": ("panel", '''**({} if h == have else {"nodes": nodes})}''', '''**{"nodes": nodes}}'''),
    "blockdrift": ("panel", '''LIVE_BACKFILL, LIVE_BACKFILL_MAX, LIVE_BACKFILL_S, LIVE_BACKFILL_WAIT = 200, 1000, 1.0, 10.0''',
                   '''LIVE_BACKFILL, LIVE_BACKFILL_MAX, LIVE_BACKFILL_S, LIVE_BACKFILL_WAIT = 100, 1000, 1.0, 10.0'''),
    "renamelose": ("block", '''                if moved:                                     # renamed: the old one to its end, then the new from 0
                    self._lines(self.f.read())''', '''                if moved:                                     # renamed: the old one to its end, then the new from 0
                    pass'''),
    "truncstuck": ("block", '''                elif st.st_size < self.f.tell():              # truncated in place: again from 0''',
                   '''                elif False:              # truncated in place: again from 0'''),
    "nogap": ("block", '''            self.gap = True\n        self._open(None)''', '''            self.gap = False\n        self._open(None)'''),
    "floodfree": ("block", '''            if self.n > self.cap:\n                self.skip += 1''', '''            if False:\n                self.skip += 1'''),
    "andjournal": ("block", '''        a += (["+"] if i else []) + g''', '''        a += g'''),
    "respawn": ("block", '''            else:\n                self.jnext = self.jstart + 5''', '''            else:\n                self._jopen()'''),
    "sniunit": ("block", '''        return "sni" if live_text(e.get("MESSAGE")).startswith("swg-sni:") else "noded"''', '''        return "noded"'''),
    "meshiface": ("block", '''            return ("mesh:" if kind == "iface:" and name.startswith(LIVE_MESH_PRE) else kind) + name''',
                  '''            return kind + name'''),
    "ifacemesh": ("noded", '''            ns = [n for n in ifaces if n.startswith(LIVE_MESH_PRE) == mesh and name in ("*", n)]''',
                  '''            ns = [n for n in ifaces if name in ("*", n)]'''),
    "nostop": ("noded", '''        for rid in [k for k in _LIVE if k not in want]:\n            _LIVE.pop(rid)["stop"].set()''',
               '''        for rid in []:\n            _LIVE.pop(rid)["stop"].set()'''),
    "nofirst": ("noded", '''            if (pend or not said) and now - t0 >= LIVE_BACKFILL_S and now - last >= rq["iv"]:''',
                '''            if pend and now - t0 >= LIVE_BACKFILL_S and now - last >= rq["iv"]:'''),
    "offread": ("noded", '''            st[s] = "off" if off else "ok"\n            units.add("swg-noded.service")''',
                '''            st[s] = "ok"\n            units.add("swg-noded.service")'''),
    "dockeriface": ("noded", '''            elif kind in ("iface", "kernel", "p2p"):\n                st[s] = "unavailable"''',
                    '''            elif kind in ("kernel", "p2p"):\n                st[s] = "unavailable"'''),
    "syncloop": ("noded", '''                threading.Thread(target=_live_run, args=(rq, list((node_cfg.get("interfaces") or {}).keys())),
                                 daemon=True, name="swg-logs-" + rid).start()''',
                 '''                _live_run(rq, list((node_cfg.get("interfaces") or {}).keys()))'''),
    "pumpdrop": ("noded", '''            _log_write(prio or LOG_INFO, ln[2:] if prio else ln)''', '''            pass'''),
    "pendcount": ("noded", '''                pend = [[pend[cut - 1][0], "!skip", 4, str(_live_skipped(pend[:cut]))]] + pend[cut:]''',
                  '''                pend = [[pend[cut - 1][0], "!skip", 4, str(cut - 1)]] + pend[cut:]'''),
    "firstspin": ("noded", '''            if (pend or not said) and now - t0 >= LIVE_BACKFILL_S and now - last >= rq["iv"]:''',
                  '''            if (not said and now - t0 >= LIVE_BACKFILL_S) or (pend and now - last >= rq["iv"]):'''),
    "nochunk": ("noded", '''        if n and size > LIVE_POST_BYTES:\n            break''', '''        if False:\n            break'''),
    "panelforever": ("panel", '''        while not rec["stop"].is_set() and time.time() <= rec["lease"]:''', '''        while not rec["stop"].is_set():'''),
    "strkey": ("panel", '''not hmac.compare_digest(key.encode("utf-8", "replace"), _live_key(rec, nid).encode())''',
               '''not hmac.compare_digest(key, _live_key(rec, nid))'''),
    "deepjson": ("panel", '''        except Exception:\n            code, obj = 400, {"ok": False, "error": "invalid body", "code": "bad_request"}''',
                 '''        except (ValueError, zlib.error):\n            code, obj = 400, {"ok": False, "error": "invalid body", "code": "bad_request"}'''),
    "curstale": ("panel", '''        elif cur is not None:''', '''        elif False:'''),
    "backfillcut": ("block", '''            if el < LIVE_BACKFILL_S or (self.p is not None and self.jback and el < LIVE_BACKFILL_WAIT):''',
                    '''            if el < LIVE_BACKFILL_S:'''),
    "noselect": ("panel", "import secrets\nimport select\nimport shutil\n", "import secrets\nimport shutil\n"),
    "nojournal": ("update", '''    ensure_log_ns swg-panel swg-panel-server.service swg-sub.service swg-netctl.service swg-update.service
    ensure_panel_journal
''', '''    ensure_log_ns swg-panel swg-panel-server.service swg-sub.service swg-netctl.service swg-update.service
'''),
}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PROG.items()}
if PLANT:
    f, a, b = PLANTS[PLANT]
    for f in (("noded", "panel") if f == "block" else (f,)):   # "block": the reader, planted in BOTH copies alike
        assert SRC[f].count(a) == 1, "plant anchor not unique/absent — this run would measure nothing: " + PLANT
        SRC[f] = SRC[f].replace(a, b)


def write_prog(key, name=None):
    p = os.path.join(tempfile.mkdtemp(prefix="loglive-prog-", dir=TMP), name or os.path.basename(PROG[key]))
    open(p, "w", encoding="utf-8").write(SRC[key])
    os.chmod(p, 0o755)
    return p


def load(key, env=None):
    old = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    ld = importlib.machinery.SourceFileLoader("ll_" + key + str(time.monotonic_ns()), write_prog(key))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(ld.name, ld))
    try:
        ld.exec_module(m)
    except SystemExit:
        pass
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    sys.excepthook, threading.excepthook = sys.__excepthook__, threading.__excepthook__
    m._LOG_STREAM = io.StringIO()
    m._LOG_JOURNAL = False
    return m


def guarded(name, fn):
    """Run one section's body; a plant that makes it raise fails ITS check rather than crashing the gate."""
    try:
        fn()
    except Exception as e:
        check(name + " (raised)", False, "%s: %s" % (type(e).__name__, e))


# ── [1] the wire, against real panels ────────────────────────────────────────────────────────────────────────────────
print("[1] the wire")


def start_panel(src_path, tag, env=None):
    d = os.path.join(TMP, "panel-" + tag)
    state = os.path.join(d, "state"); os.makedirs(state)
    stats = os.path.join(d, "stats"); os.makedirs(stats)
    nodes = os.path.join(state, "nodes.json")
    json.dump({"n1": {"id": "n1", "name": "n1", "links": {}, "ifaces": {}},
               "n2": {"id": "n2", "name": "n2", "links": {}, "ifaces": {}}}, open(nodes, "w"))
    open(os.path.join(state, "users.json"), "w").write("{}\n")
    fleet = os.path.join(d, "fleet.json")
    json.dump({"nodes_path": nodes, "roster_path": os.path.join(state, "users.json"), "stats_dir": stats}, open(fleet, "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    lg = open(os.path.join(d, "panel.log"), "w+")
    p = subprocess.Popen([sys.executable, src_path], stdout=lg, stderr=subprocess.STDOUT,
                         env={**os.environ, "SWG_PANEL_FLEET": fleet, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                              "SWG_PANEL_PORT": str(port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                              "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", **(env or {})})
    for _ in range(300):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/healthz" % port, timeout=2)
            break
        except Exception:
            if p.poll() is not None:
                sys.exit("panel exited: " + open(lg.name).read()[-2000:])
            time.sleep(0.1)
    return p, port, state


def req(port, path, data=None, token=None, raw=None, hdrs=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    r = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=body,
                               headers={"Content-Type": "application/json",
                                        **({"Authorization": "Bearer " + token} if token else {}), **(hdrs or {})})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            out, code = resp.read(), resp.status
            if resp.headers.get("Content-Encoding") == "gzip":
                out = gzip.decompress(out)
    except urllib.error.HTTPError as e:
        out, code = e.read(), e.code
    return code, json.loads(out or b"{}")


def sync(port, tok, nid="n1", live=True):
    snap = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {},
            "log": {"mb": 100, "used_mb": 1.0, **({"live": 1} if live else {})}}
    code, r = req(port, "/api/node/sync", {"snapshot": snap}, tok)
    assert code == 200, (code, r)
    return r


def post_lines(port, rid, key, lines, st=None, now=None, gz=True):
    body = {"id": rid, "key": key, "now": now if now is not None else time.time(), "lines": lines, "cur": {"j": "c1"}}
    if st is not None:
        body["st"] = st
    raw = json.dumps(body).encode()
    return req(port, "/api/node/logs", raw=gzip.compress(raw) if gz else raw, hdrs={"Content-Encoding": "gzip"} if gz else {})


ref_src = os.path.join(TMP, "ref-swg-panel-server")
open(ref_src, "wb").write(subprocess.run(["git", "-C", ROOT, "show", REF + ":swg-panel-server"], capture_output=True,
                                         check=True).stdout)
procs = []
CTX = {}


def sec1():
    pa, port_a, _ = start_panel(ref_src, "refa"); procs.append(pa)
    pb, port_b, _ = start_panel(ref_src, "refb"); procs.append(pb)
    pn, port_n, state_n = start_panel(write_prog("panel"), "new"); procs.append(pn)
    toks = {}
    for port in (port_a, port_b, port_n):
        toks[port] = {n: req(port, "/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in ("n1", "n2")}
    ra, rb, rn = (sync(port, toks[port]["n1"]) for port in (port_a, port_b, port_n))
    ra, rb, rn = (sync(port, toks[port]["n1"]) for port in (port_a, port_b, port_n))   # a second, steady sync
    vol = {k for k in set(ra) | set(rb) if json.dumps(ra.get(k), sort_keys=True) != json.dumps(rb.get(k), sort_keys=True)}
    diff = [k for k in set(ra) | set(rn) if k not in vol and json.dumps(ra.get(k)) != json.dumps(rn.get(k))]
    check("[1] an idle fleet's sync reply is byte-identical to the build before the viewer (but what the old build's own "
          "instances disagree on: %s)" % sorted(vol), list(rn) == list(ra) and not diff, (diff, set(rn) ^ set(ra)))
    c, o = req(port_n, "/api/logs/live", {"nodes": ["n1"], "src": ["noded", "turn:*"]})
    check("[1] a viewer opens a request", c == 200 and LIVE_ID.match(o["data"]["id"]), (c, o))
    rid = o["data"]["id"]
    r1, r2 = sync(port_n, toks[port_n]["n1"]), sync(port_n, toks[port_n]["n2"], "n2")
    e = (r1.get("logs") or [{}])[0]
    check("[1] the node it names gets `logs` [{id, src, iv, cap, lease, key}]",
          e.get("id") == rid and e.get("src") == ["noded", "turn:*"] and e.get("iv") == 1 and e.get("cap") == 200
          and 1 <= e.get("lease", 0) <= 15 and e.get("key", "").startswith("n1."), r1.get("logs"))
    check("[1] a node the request does not name gets no `logs` at all", "logs" not in r2, r2.get("logs"))
    req(port_n, "/api/logs/live/close", {"id": rid})
    check("[1] closed: the key is gone from the reply", "logs" not in sync(port_n, toks[port_n]["n1"]))
    c, o = req(port_n, "/api/node/logs", raw=gzip.compress(b"not json " * 50000), hdrs={"Content-Encoding": "gzip"})
    check("[1] nothing open: a log post is refused before its body is unpacked or parsed (404, not the parser's 400)",
          c == 404 and o.get("code") == "gone", (c, o))
    CTX.update(port=port_n, toks=toks[port_n], state=state_n)


LIVE_ID = re.compile(r"^[0-9a-f]{16}$")
try:
    guarded("[1]", sec1)

    # ── [2] POST /api/node/logs ──────────────────────────────────────────────────────────────────────────────────────
    print("[2] POST /api/node/logs")

    def sec2():
        port, toks = CTX["port"], CTX["toks"]
        rid = req(port, "/api/logs/live", {"nodes": ["n1", "n2"], "src": ["noded"]})[1]["data"]["id"]
        key1 = sync(port, toks["n1"])["logs"][0]["key"]
        key2 = sync(port, toks["n2"], "n2")["logs"][0]["key"]
        t = int(time.time() * 1e6)
        c, o = post_lines(port, rid, key1, [[t, "noded", 6, "hello"], [t + 1, "noded", 3, "bad"]], st={"noded": "ok"})
        v = req(port, "/api/logs/live?id=%s&after=0" % rid)[1].get("data") or {}
        check("[2] gzip lines reach the viewer, with no node token", c == 200 and [l[1:] for l in v.get("lines", [])]
              == [["n1", t, "noded", 6, "hello"], ["n1", t + 1, "noded", 3, "bad"]], (c, o, v.get("lines")))
        c, o = post_lines(port, rid, "n1." + "0" * 32, [[t, "noded", 6, "x"]])
        c2, _ = post_lines(port, rid, key2.replace("n2.", "n1."), [[t, "noded", 6, "x"]])
        check("[2] a wrong key, or another node's, is 403", c == 403 and c2 == 403, (c, c2))
        c, o = post_lines(port, "f" * 16, key1, [[t, "noded", 6, "x"]])
        check("[2] a request the panel does not have is 404 (the node stops)", c == 404 and o.get("code") == "gone", (c, o))
        bomb = gzip.compress(b'{"id": "' + rid.encode() + b'", "lines": [' + b" " * (6 << 20) + b"]}", 9)
        c, o = req(port, "/api/node/logs", raw=bomb, hdrs={"Content-Encoding": "gzip"})
        check("[2] a gzip bomb (6 MiB unpacked) is refused", c == 413, (c, o, len(bomb)))
        c, o = req(port, "/api/node/logs", raw=b"x" * ((1 << 20) + 10), hdrs={"Content-Encoding": "gzip"})
        check("[2] a body over 1 MiB is refused", c == 413, (c, o))
        try:
            c, o = req(port, "/api/node/logs", raw=gzip.compress(b"[" * 200000), hdrs={"Content-Encoding": "gzip"})
        except Exception as e:
            c, o = repr(e)[:80], None
        check("[2] a deeply nested body is a 400, never a dropped connection", c == 400, (c, o))
        # no node token, no api(): in-process, nodes_load counted
        P = load("panel")
        calls = []
        P.nodes_load = lambda path, _n=P.nodes_load: (calls.append(path), _n(path))[1]
        P.Handler.deps = {"nodes_path": os.path.join(CTX["state"], "nodes.json")}
        P.Handler.headers = None

        class H:
            pass
        h = H()
        sent = []
        rec_id = P.live_open(["n1"], ["noded"], {"n1"})[1]["data"]["id"]
        k = P._live_key(P._LIVE_REQS[rec_id], "n1")
        body = gzip.compress(json.dumps({"id": rec_id, "key": k, "lines": [[1, "noded", 6, "x"]]}).encode())
        h.headers = {"Content-Length": str(len(body)), "Content-Encoding": "gzip", "Authorization": "Bearer nope"}
        h.rfile = io.BytesIO(body)
        h._send = lambda code, obj: sent.append((code, obj))
        h._body_len = lambda cap=0: P.Handler._body_len(h, cap)
        h._node_token = lambda: P.Handler._node_token(h)
        try:
            P.Handler._node_logs(h)
        except Exception as e:
            sent.append(("raised", repr(e)))
        check("[2] the log POST never reads the node store (no node-token check)", not calls and sent and sent[0][0] == 200,
              (calls, sent))
        src = SRC["panel"]
        m = re.search(r"\n    def _node_logs\(self\):.*?\n    def ", src, re.S)
        code_only = re.sub(r'"""(.|\n)*?"""', "", m.group(0)) if m else ""
        check("[2] the route takes no _api_lock and is a node-door route",
              m and "_api_lock" not in code_only and '"/api/node/logs"' in src.split("\nNODE_DOOR_POST = ")[1][:400])
        gi = src.index('if path == "/api/logs/live":   # the log viewer')
        check("[2] the viewer's poll is answered before api() (which parses the node store on every call)",
              gi < src.index('code, obj = api("GET", path, parse_qs(u.query), {}, self.deps)', gi - 2000))
        CTX["rid2"] = rid
    guarded("[2]", sec2)
finally:
    for p in procs:
        p.terminate()

# ── [3] the store (in-process, a clock of our own) ───────────────────────────────────────────────────────────────────
print("[3] the store")


def sec3():
    P = load("panel")
    T = [1000.0]
    known = {"a", "b", "c", "old", "gone"}
    c, o = P.live_open(["a", "b", "zz"], ["noded", "bad src!", "turn:*"], known, now=T[0])
    rid = o["data"]["id"]
    rec = P._LIVE_REQS[rid]
    check("[3] unknown nodes and malformed sources are dropped", rec["nodes"] == ["a", "b"] and rec["src"] == ["noded", "turn:*"],
          (rec["nodes"], rec["src"]))
    T[0] += 10
    P.live_view(rid, 0, "", {}, {}, 30, now=T[0])
    check("[3] the viewer's poll renews the lease", rec["lease"] == T[0] + P.LIVE_LEASE, (rec["lease"], T[0]))
    T[0] += P.LIVE_LEASE + 1
    check("[3] a lapsed request is gone: the viewer's poll 404s, the node's post 404s, no reply carries it",
          P.live_view(rid, 0, "", {}, {}, 30, now=T[0]) is None
          and P.live_absorb({"id": rid, "key": "a.x"}, now=T[0])[0] == 404 and P.live_reply("a", now=T[0]) is None
          and rec["stop"].is_set())
    ids = [P.live_open(["a"], ["noded"], known, now=T[0])[1]["data"]["id"] for _ in range(4)]
    c, o = P.live_open(["a"], ["noded"], known, now=T[0])
    check("[3] a 5th viewer is refused (429), and nobody is evicted", c == 429 and all(i in P._LIVE_REQS for i in ids), (c, o))
    c, o = P.live_open(["a"], ["sni"], known, replace=ids[0], now=T[0])
    check("[3] a replace frees its own slot", c == 200 and ids[0] not in P._LIVE_REQS, (c, o))
    for i in list(P._LIVE_REQS):
        P.live_close(i)
    rid = P.live_open(["a", "b"], ["noded"], known, now=T[0])[1]["data"]["id"]
    rec = P._LIVE_REQS[rid]
    ka = P._live_key(rec, "a")
    for n in range(3):
        P.live_absorb({"id": rid, "key": ka, "lines": [[i, "noded", 6, "l%d" % i] for i in range(n * 2000, n * 2000 + 2000)]},
                      now=T[0])
    v = P.live_view(rid, rec["seq"] - 3, "", {}, {}, 30, now=T[0])
    check("[3] 5 000 lines are kept, and a poll gets exactly the lines after its seq",
          len(rec["buf"]) == P.LIVE_BUF and rec["seq"] == 6000 and [l[5] for l in v["lines"]] == ["l5997", "l5998", "l5999"],
          (len(rec["buf"]), rec["seq"], [l[5] for l in v["lines"]]))
    v = P.live_view(rid, 0, "", {}, {}, 30, now=T[0])
    check("[3] a poll from 0 after the buffer wrapped gets what is kept", len(v["lines"]) == P.LIVE_BUF and v["lines"][0][0] == 1001)
    check("[3] the flood cap and the post interval scale with the request (200 lines/s ≤ 5 nodes … 5 at 200; 1 s … 8 s)",
          (P.live_cap(2), P.live_cap(5), P.live_cap(200), P.live_iv(2), P.live_iv(25), P.live_iv(26), P.live_iv(200))
          == (200, 200, 5, 1, 1, 2, 8), (P.live_cap(200), P.live_iv(200)))
    P.live_absorb({"id": rid, "key": ka, "lines": [], "now": T[0] + 95.4}, now=T[0])
    kb = P._live_key(rec, "b")
    P.live_absorb({"id": rid, "key": kb, "lines": [], "now": T[0] + 1.2, "st": {"noded": "ok", "x": "weird"}}, now=T[0])
    v = P.live_view(rid, rec["seq"], "", {}, {}, 30, now=T[0])
    check("[3] a node's clock offset is measured (≥ 2 s), a small one is not", v["nodes"]["a"].get("off") == 95
          and "off" not in v["nodes"]["b"] and v["nodes"]["b"]["st"] == {"noded": "ok"}, v["nodes"])
    rid2 = P.live_open(["a", "c", "old", "gone", "panel"], ["noded"], known, now=T[0])[1]["data"]["id"]
    P.live_absorb({"id": rid2, "key": P._live_key(P._LIVE_REQS[rid2], "a"), "lines": []}, now=T[0])
    for _ in range(50):                               # the panel's own reader acks from its thread
        if "panel" in P._LIVE_REQS[rid2]["acked"]:
            break
        time.sleep(0.05)
    snaps = {"c": {"log": {"live": 1}}, "old": {"log": {"mb": 100}}, "gone": {"log": {"live": 1}}}
    seen = {"c": T[0] - 3, "old": T[0] - 3, "gone": T[0] - 300}
    P.live_reply("c", now=T[0])
    v = P.live_view(rid2, 0, "", snaps, seen, 30, now=T[0])
    st0 = {k: x["state"] for k, x in v["nodes"].items()}
    P.live_view(rid2, 0, "", snaps, seen, 30, now=T[0] + 10)                     # the viewer keeps polling
    seen = {k: v + P.LIVE_NOANSWER_S + 1 for k, v in seen.items()}
    v2 = P.live_view(rid2, 0, "", snaps, seen, 30, now=T[0] + P.LIVE_NOANSWER_S + 1)
    check("[3] each box's state: ok · waiting → no answer · old (update the node) · offline · the panel answers itself",
          st0 == {"a": "ok", "c": "waiting", "old": "old", "gone": "offline", "panel": "ok"}
          and v2["nodes"]["c"]["state"] == "noanswer", (st0, v2["nodes"]["c"]))
    v3 = P.live_view(rid2, 0, v2["h"], snaps, seen, 30, now=T[0] + P.LIVE_NOANSWER_S + 1)
    check("[3] the states block is sent only when it changed", "nodes" not in v3 and v3["h"] == v2["h"], list(v3))
    rid4 = P.live_open(["a"], ["noded"], known)[1]["data"]["id"]
    try:
        r1 = P.live_absorb({"id": rid4, "key": "a.é" + "x" * 31, "lines": []})[0]
        r2 = P.live_absorb({"id": rid4, "key": P._live_key(P._LIVE_REQS[rid4], "a"), "lines": [], "now": float("inf"),
                            "cur": {"f": {"/var/lib/swg-noded/wdtt/wdtt%d/server.log" % i: [i, i] for i in range(60)}}})[0]
    except Exception as e:
        r1 = r2 = repr(e)
    check("[3] remote input never raises: a key that is not ASCII is 403, an infinite clock is ignored; a docker node's "
          "long resume point (60 files) is kept",
          r1 == 403 and r2 == 200 and len(P._LIVE_REQS[rid4]["cur"].get("a", {}).get("f", {})) == 60, (r1, r2))
    P.live_absorb({"id": rid4, "key": P._live_key(P._LIVE_REQS[rid4], "a"), "lines": [], "cur": {"j": "x" * 9000}})
    check("[3] a resume point too big to keep drops the stored one (a restart starts afresh, not from a stale point)",
          "a" not in P._LIVE_REQS[rid4]["cur"], list(P._LIVE_REQS[rid4]["cur"]))
    for i in list(P._LIVE_REQS):
        P.live_close(i)
    lf = os.path.join(TMP, "panel-own.log")
    open(lf, "w").write("")
    P.PANEL_LOG_FILE["path"] = lf
    P.LIVE_LEASE = 1
    rid5 = P.live_open(["panel"], ["panel"], known)[1]["data"]["id"]
    time.sleep(0.3)
    th = [t for t in threading.enumerate() if t.name == "swg-logs-" + rid5]
    time.sleep(2.5)                                   # nobody polls, nothing syncs: only the reader itself can notice
    check("[3] the panel's own reader stops at its lease by itself (no poll, no sync), and frees the slot",
          th and not th[0].is_alive() and rid5 not in P._LIVE_REQS, (th, list(P._LIVE_REQS)))
    P.PANEL_LOG_FILE["path"] = None


guarded("[3]", sec3)

# ── [4] the reader ───────────────────────────────────────────────────────────────────────────────────────────────────
print("[4] the reader")
N = load("noded", {"SWG_NODED_STATE": os.path.join(TMP, "noded-state")})


def block(s):
    i = s.index("# ── the live log reader (docs")
    return s[i:s.index("# ── end of the live log reader", i)]


def drain(rd, secs, step=0.2):
    out, end = [], time.monotonic() + secs
    while time.monotonic() < end:
        out += rd.poll(step)
    return out


def ts(off=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + off))


def sec4():
    check("[4] the reader is one block, byte-identical in swg-noded and swg-panel-server", block(SRC["noded"]) == block(SRC["panel"]))
    d = tempfile.mkdtemp(dir=TMP)
    P_, Q = os.path.join(d, "n.log"), os.path.join(d, "d.log")
    w = lambda p, s: open(p, "a").write(s)
    for i in range(250):
        w(P_, "%s I old%d\n" % (ts(), i))
    w(P_, "%s W swg-sni: a.example\n" % ts())
    rd = N.LiveReader({"noded", "sni"}, files=[(P_, N.live_noded_src, "ours")], cap=1000)
    out = drain(rd, 1.3)
    check("[4] the backfill is the last 200 lines per source, sources told apart by the prefix",
          len([l for l in out if l[1] == "noded"]) == 200 and out[0][3] == "old50"
          and [l[1:] for l in out if l[1] == "sni"] == [["sni", 4, "swg-sni: a.example"]], (len(out), out[:1], out[-1:]))
    w(P_, "%s I a1\n" % ts()); w(P_, "%s I a2\n" % ts())
    os.replace(P_, P_ + ".1")
    w(P_, "%s I b1\n" % ts())
    out = drain(rd, 0.5)
    check("[4] a renamed file: its last lines, then the new file — nothing lost, nothing repeated",
          [l[3] for l in out] == ["a1", "a2", "b1"], [l[3] for l in out])
    # a flood at the rotation: more than one read's worth (256 KiB) still unread in the renamed file — its end comes too
    PF = os.path.join(d, "flood-rot.log")
    open(PF, "w").close()
    rdf = N.LiveReader({"noded"}, files=[(PF, N.live_noded_src, "ours")], cap=100000)
    drain(rdf, 1.2)
    w(PF, "".join("%s I f%04d %s\n" % (ts(), i, "y" * 90) for i in range(3000)))
    os.replace(PF, PF + ".1")
    w(PF, "%s I after\n" % ts())
    out = drain(rdf, 0.8)
    rdf.close()
    check("[4] a flood at the rotation: the renamed file is read to its end (past one read's 256 KiB), then the new one",
          len(out) == 3001 and out[-1][3] == "after" and out[2999][3].startswith("f2999"), (len(out), out[-1:]))
    rdq = N.LiveReader({"dns"}, files=[(Q, "dns", "syslog")], cap=1000)
    drain(rdq, 1.2)
    stamp = time.strftime("%b %e %H:%M:%S")
    for i in range(20):
        w(Q, "%s dnsmasq[7]: q1 %d\n" % (stamp, i))
    drain(rdq, 0.3)
    open(Q, "w").close()
    w(Q, "%s dnsmasq[7]: q2\n" % stamp)
    out = drain(rdq, 0.5)
    check("[4] a copy-truncated file is read again from its start", [l[3] for l in out] == ["q2"], out)
    rdq.close()
    cur = rd.cursor()
    rd.close()
    w(P_, "%s I c1\n" % ts())
    os.replace(P_, P_ + ".1")
    w(P_, "%s I c2\n" % ts())
    rd2 = N.LiveReader({"noded"}, files=[(P_, N.live_noded_src, "ours")], cur=cur, cap=1000)
    out = drain(rd2, 1.3)
    check("[4] a restarted reader resumes where the last one stopped, across a rename", [l[3] for l in out] == ["c1", "c2"],
          [l[3] for l in out])
    rd2.close()
    rd3 = N.LiveReader({"noded"}, files=[(P_, N.live_noded_src, "ours")], cur={"f": {P_: [1, 7]}}, cap=1000)
    out = drain(rd3, 1.3)
    check("[4] a resume point that is gone says so (\"!gap\") and starts afresh", out and out[0][1] == "!gap", out[:2])
    rd3.close()
    rd4 = N.LiveReader({"noded"}, files=[(P_, N.live_noded_src, "ours")], cap=5)
    drain(rd4, 1.2)
    time.sleep(1.0 - time.monotonic() % 1 + 0.05)
    for i in range(12):
        w(P_, "%s I f%d\n" % (ts(), i))
    out = drain(rd4, 1.6)
    check("[4] the flood cap: 5 a second, then one marker with how many were skipped",
          [l[3] for l in out if l[1] == "noded"] == ["f0", "f1", "f2", "f3", "f4"]
          and [l[3] for l in out if l[1] == "!skip"] == ["7"], out)
    rd4.close()
    E = lambda **k: k
    cases = [(E(_SYSTEMD_UNIT="swg-noded.service", MESSAGE="reconcile"), "noded"),
             (E(_SYSTEMD_UNIT="swg-noded.service", MESSAGE="swg-sni: x"), "sni"),
             (E(_SYSTEMD_UNIT="swg-noded.service", SYSLOG_IDENTIFIER="dnsmasq", MESSAGE="query"), "dns"),
             (E(_PID="1", _SYSTEMD_UNIT="init.scope", UNIT="swg-relay@awg0.service", MESSAGE="Started"), "relay:awg0"),
             (E(_SYSTEMD_UNIT="swg-wdtt-wdtt1.service"), "turn:wdtt1"), (E(_SYSTEMD_UNIT="vk-turn-proxy-x-1.service"), "turn:x-1"),
             (E(_SYSTEMD_UNIT="awg-quick@awg0.service"), "iface:awg0"), (E(_TRANSPORT="kernel", MESSAGE="swg-p2p IN=x"), "p2p"),
             (E(_SYSTEMD_UNIT="awg-quick@swg_ab12.service"), "mesh:swg_ab12"),
             (E(_PID="1", _SYSTEMD_UNIT="init.scope", UNIT="wg-quick@swg_x.service", MESSAGE="Started"), "mesh:swg_x"),
             (E(_TRANSPORT="kernel", MESSAGE=[111, 107]), "kernel"), (E(_SYSTEMD_UNIT="swg-panel-server.service"), "panel"),
             (E(_SYSTEMD_UNIT="sshd.service"), None), (E(_SYSTEMD_UNIT="session-1.scope"), None)]
    bad = [(c, N.live_journal_src(c)) for c, want in cases if N.live_journal_src(c) != want]
    check("[4] journal lines are filed by unit, identifier, prefix and transport", not bad, bad)
    a = N.live_journal_argv(["journalctl", "--namespace=+swg-node"], ["swg-noded.service", "swg-relay@awg0.service"], True, None, 400)
    check("[4] journalctl's matches are OR-ed groups (`+`), from the last n lines or after a cursor",
          a[a.index("-n"):] == ["-n", "400", "_SYSTEMD_UNIT=swg-noded.service", "_SYSTEMD_UNIT=swg-relay@awg0.service", "+",
                                "_PID=1", "UNIT=swg-noded.service", "UNIT=swg-relay@awg0.service", "+", "_TRANSPORT=kernel"]
          and "--after-cursor=s=1" in N.live_journal_argv(["journalctl"], ["u.service"], False, "s=1", 9), a)
    # a fake journalctl: refuses a cursor (rc 1), otherwise prints two entries and ends (a dying follower)
    fj, spawns = os.path.join(d, "fakejournalctl"), os.path.join(d, "spawns")
    open(fj, "w").write("#!/usr/bin/env python3\nimport sys, json\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                        "if any(a.startswith('--after-cursor=') for a in sys.argv): sys.exit(1)\n"
                        "for i in range(2): print(json.dumps({'__CURSOR': 'c%%d' %% i, '__REALTIME_TIMESTAMP': str(1000 + i),"
                        " '_SYSTEMD_UNIT': 'swg-noded.service', 'PRIORITY': '6', 'MESSAGE': 'j%%d' %% i}))\n" % spawns)
    os.chmod(fj, 0o755)
    rd5 = N.LiveReader({"noded"}, journal=lambda cur, n: N.live_journal_argv([fj], ["swg-noded.service"], False, cur, n),
                       cur={"j": "bad"}, cap=1000)
    out = drain(rd5, 3.0)
    runs = open(spawns).read().splitlines()
    check("[4] a cursor journalctl refuses → \"!gap\", a backfill read (no -f) and the follower after its last line; "
          "a journalctl that ends is not respawned in a loop",
          out and out[0][1] == "!gap" and [l[3] for l in out[1:3]] == ["j0", "j1"] and len(runs) == 3
          and "--after-cursor=bad" in runs[0] and "-n" in runs[1] and "-f" not in runs[1].split()
          and "--after-cursor=c1" in runs[2] and "-f" in runs[2].split(), (out[:3], runs))
    rd5.close()
    # a cold journal: the backfill comes in two halves 1.5 s apart — still all backfill, none of it "skipped"
    fs = os.path.join(d, "slowjournal")
    open(fs, "w").write("#!/usr/bin/env python3\nimport sys, json, time\n"
                        "def out(a, b):\n    for i in range(a, b): print(json.dumps({'__CURSOR': 'c%d' % i, '__REALTIME_TIMESTAMP': str(1000 + i),"
                        " '_SYSTEMD_UNIT': 'swg-noded.service', 'PRIORITY': '6', 'MESSAGE': 'b%d' % i}), flush=True)\n"
                        "if '-f' in sys.argv: time.sleep(30)\nout(0, 300); time.sleep(1.5); out(300, 600)\n")
    os.chmod(fs, 0o755)
    rd8 = N.LiveReader({"noded"}, journal=lambda cur, n: N.live_journal_argv([fs], ["swg-noded.service"], False, cur, n), cap=5)
    out = drain(rd8, 3.5)
    rd8.close()
    check("[4] a slow (cold) journal's backfill is still the backfill: the last 200, none reported skipped",
          [l[3] for l in out] == ["b%d" % i for i in range(400, 600)], (len(out), out[:1], [l for l in out if l[1] == "!skip"]))
    # a container stream through a fake Engine API socket
    sp = os.path.join(d, "docker.sock")
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(sp)
    srv.listen(4)
    got = []

    def serve():
        for k in range(2):
            c, _ = srv.accept()
            q = c.recv(4096).decode()
            got.append(q.split("\r\n")[0])
            c.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: application/vnd.docker.multiplexed-stream\r\n\r\n")
            for i, t in enumerate(("2026-10-05T10:00:00.5Z", "2026-10-05T10:00:01.123456789Z")):
                p = ("%s out%d\n" % (t, i)).encode()
                c.sendall(bytes([1, 0, 0, 0]) + len(p).to_bytes(4, "big") + p)
            time.sleep(0.6)
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    rd6 = N.LiveReader({"relay:*"}, ctrs=[("swg-relay-awg0", "relay:awg0")], sock=sp, cap=1000)
    out = drain(rd6, 1.3)
    c6 = rd6.cursor()
    rd6.close()
    rd7 = N.LiveReader({"relay:*"}, ctrs=[("swg-relay-awg0", "relay:awg0")], sock=sp, cur=c6, cap=1000)
    out7 = drain(rd7, 1.3)
    rd7.close()
    check("[4] a container's log through the Engine API: its lines, then a resume from the last one (since, no repeat)",
          [l[3] for l in out] == ["out0", "out1"] and out[1][0] == 1791194401123456 and out7 == []
          and "tail=200" in got[0] and "since=1791194401.123456789" in got[1], (out, out7, got))


guarded("[4]", sec4)

# ── [5] the node ─────────────────────────────────────────────────────────────────────────────────────────────────────
print("[5] the node")


def sec5():
    posts = []
    N.post_json = lambda url, tok, obj, panel, timeout=20, source_ip="", peer=None, gz=False: (
        posts.append((url, obj, gz)), (POSTCODE[0], {}))[1]
    POSTCODE = [200]
    d = tempfile.mkdtemp(dir=TMP)
    lf = os.path.join(d, "n.log")
    open(lf, "w").write("%s I hello\n" % ts())
    N._live_plan = lambda srcs, ifaces: ({"files": [(lf, N.live_noded_src, "ours")]}, {s: "ok" for s in srcs})
    N.LIVE_GRACE = 0
    rq = lambda i, **k: dict({"id": "%016x" % i, "src": ["noded"], "iv": 1, "cap": 200, "lease": 3, "key": "n1.k"}, **k)
    t = time.monotonic()
    th = threading.Thread(target=N.live_logs_take, args=([rq(1)], "https://p/api/node/sync", {"token": "T"}, {"interfaces": {}}),
                          daemon=True)
    th.start()
    th.join(1.0)                                      # the sync loop's call: back at once, or it holds the loop
    took = time.monotonic() - t
    check("[5] a request starts a reader thread; the sync loop is not held", not th.is_alive() and took < 0.5
          and "%016x" % 1 in N._LIVE, took)
    if th.is_alive():
        raise RuntimeError("live_logs_take did not return: the rest of [5] cannot run")
    time.sleep(1.6)
    first = [p for p in posts if p[1]["id"] == "%016x" % 1]
    check("[5] the first post carries each source's state and the backfill, gzip, to /api/node/logs",
          first and first[0][0] == "https://p/api/node/logs" and first[0][2] and first[0][1].get("st") == {"noded": "ok"}
          and [l[3] for l in first[0][1]["lines"]] == ["hello"], first[:1])
    open(lf, "w").close()
    posts.clear()
    N.live_logs_take([rq(2)], "https://p/api/node/sync", {"token": "T"}, {"interfaces": {}})
    time.sleep(0.3)
    check("[5] a reader the reply no longer names stops", "%016x" % 1 not in N._LIVE)
    time.sleep(1.4)
    first = [p for p in posts if p[1]["id"] == "%016x" % 2]
    check("[5] the first post goes even with no lines (the viewer learns the sources' states)",
          first and first[0][1].get("st") == {"noded": "ok"} and first[0][1]["lines"] == [], first[:1])
    POSTCODE[0] = 404
    open(lf, "a").write("%s I more\n" % ts())
    time.sleep(1.5)
    check("[5] a 404 (the request is gone) stops the reader", "%016x" % 2 not in N._LIVE)
    POSTCODE[0] = 200
    N.live_logs_take([rq(3, lease=1)], "https://p/api/node/sync", {"token": "T"}, {"interfaces": {}})
    time.sleep(2.0)
    check("[5] with no reply renewing it, the lease stops the reader", "%016x" % 3 not in N._LIVE)
    N.live_logs_take([rq(i) for i in range(10, 16)], "https://p/api/node/sync", {"token": "T"}, {"interfaces": {}})
    check("[5] at most 4 readers", len(N._LIVE) == 4, len(N._LIVE))
    N.live_logs_take(None, "https://p/api/node/sync", {"token": "T"}, {"interfaces": {}})
    check("[5] a reply with no `logs` stops them all", not N._LIVE)
    # the panel away: posts fail, lines pile up past LIVE_PEND_MAX twice, then it answers
    lf2 = os.path.join(d, "flood.log")
    open(lf2, "w").close()
    N._live_plan = lambda srcs, ifaces: ({"files": [(lf2, N.live_noded_src, "ours")]}, {s: "ok" for s in srcs})
    posts.clear()
    POSTCODE[0] = 0
    q = rq(40, lease=30, iv=2, cap=100000)
    q.update(stop=threading.Event(), exp=time.monotonic() + 30, url="https://p/api/node/logs", panel={"token": "T"}, cur=None)
    th = threading.Thread(target=N._live_run, args=(q, []), daemon=True)
    th.start()
    time.sleep(1.3)
    for burst in range(2):
        open(lf2, "a").write("".join("%s I l%d-%d\n" % (ts(), burst, i) for i in range(1500)))
        time.sleep(1.2)
    tries = len(posts)
    POSTCODE[0] = 200
    time.sleep(2.5)
    q["stop"].set()
    th.join(3)
    ok_posts = posts[tries:]
    sent = [ln for p_ in ok_posts for ln in p_[1]["lines"]]
    check("[5] a failing first post is retried every interval (2 s), not every poll", 1 <= tries <= 3, tries)
    check("[5] lines dropped while the panel is away are counted exactly — an earlier marker's count carried, none lost",
          N._live_skipped(sent) == 3000 and len([l for l in sent if l[1] == "!skip"]) == 1,
          (N._live_skipped(sent), len(sent), [l for l in sent if l[1] == "!skip"]))
    big = [[i, "noded", 6, "x" * 4096] for i in range(2000)]
    n = N._live_chunk(big)
    check("[5] a backlog goes in parts under the panel's limits (≤ 900 KiB of JSON a post)",
          150 < n < 250 and len(json.dumps(big[:n])) <= N.LIVE_POST_BYTES + 5000, n)
    # the source plan
    M = load("noded", {"SWG_NODED_STATE": os.path.join(TMP, "noded-plan")})
    M.NODE_KIND = "baremetal"
    M.log_ns_ok = lambda: True
    M._RELAY = {"awg0": {}}
    ud = tempfile.mkdtemp(dir=TMP)
    for u in ("vk-turn-proxy-wdttplus-56000.service", "swg-wdtt-wdtt1.service", "swg-csqtt-.service", "swg-relay@.service"):
        open(os.path.join(ud, u), "w").close()
    M.UNIT_DIR_PERSIST, M.UNIT_DIR_RUNTIME = ud, os.path.join(ud, "none")
    srcs = ["noded", "sni", "relay:*", "turn:*", "turn:nope", "iface:awg0", "p2p", "panel", "netctl"]
    plan, st = M._live_plan(srcs, ["awg0", "wg0"])
    argv = plan["journal"](None, 50)
    check("[5] bare metal: one journalctl over the namespace for the chosen units; the panel's sources are not the node's",
          st == {"noded": "ok", "sni": "ok", "relay:*": "ok", "turn:*": "ok", "turn:nope": "absent", "iface:awg0": "ok", "p2p": "ok"}
          and argv[:2] == ["journalctl", "--namespace=+swg-node"]
          and {a for a in argv if a.startswith("_SYSTEMD_UNIT=")} == {"_SYSTEMD_UNIT=" + u for u in (
              "swg-noded.service", "swg-relay@awg0.service", "vk-turn-proxy-wdttplus-56000.service", "swg-wdtt-wdtt1.service",
              "wg-quick@awg0.service", "awg-quick@awg0.service")} and "_TRANSPORT=kernel" in argv, (st, argv))
    plan, st = M._live_plan(["iface:*", "mesh:*"], ["awg0", "swg_ab12"])
    a1 = {a for a in plan["journal"](None, 5) if a.startswith("_SYSTEMD_UNIT=")}
    _p, st1 = M._live_plan(["iface:*"], ["awg0", "swg_ab12"])
    a2 = {a for a in _p["journal"](None, 5) if a.startswith("_SYSTEMD_UNIT=")}
    _p, st2 = M._live_plan(["mesh:*"], ["awg0"])
    _p, st3 = M._live_plan(["iface:swg_ab12"], ["awg0", "swg_ab12"])
    check("[5] `iface:*` is the client interfaces, `mesh:*` the mesh links (the reserved swg_ prefix); none, or a link named as an interface → \"absent\"",
          "_SYSTEMD_UNIT=awg-quick@swg_ab12.service" in a1 and "_SYSTEMD_UNIT=awg-quick@awg0.service" in a1
          and "_SYSTEMD_UNIT=awg-quick@swg_ab12.service" not in a2 and "_SYSTEMD_UNIT=awg-quick@awg0.service" in a2
          and st2 == {"mesh:*": "absent"} and st3 == {"iface:swg_ab12": "absent"}, (a1, a2, st2, st3))
    M.log_set(M.LOG_OFF)
    _p, st = M._live_plan(["noded", "relay:*", "iface:awg0", "kernel", "p2p"], ["awg0"])
    check("[5] at Off the swg journal's sources are \"off\" (nothing stored to read); the main journal's are read",
          st == {"noded": "off", "relay:*": "off", "iface:awg0": "ok", "kernel": "ok", "p2p": "off"}, st)
    M.log_set(M.LOG_INFO)
    M.NODE_KIND = "docker"
    M._host_sh_available = lambda: False
    plan, st = M._live_plan(["noded", "sni", "dns", "relay:*", "iface:*", "mesh:*", "kernel", "p2p"], ["awg0"])
    check("[5] docker: noded's file once for noded and sni, dnsmasq's file; no socket → no relay; the interfaces, the mesh "
          "links, the kernel and the P2P guard are unavailable",
          st == {"noded": "ok", "sni": "ok", "dns": "ok", "relay:*": "absent", "iface:*": "unavailable", "mesh:*": "unavailable",
                 "kernel": "unavailable", "p2p": "unavailable"} and [f[0] for f in plan["files"]] == [os.path.join(M.LOG_DIR_DOCKER, "swg-noded.log"),
                                                                              M.DNSMASQ_LOG] and not plan["ctrs"], (st, plan))
    # post_json gz, against a real listener
    got = {}

    class Hd(__import__("http.server").server.BaseHTTPRequestHandler):
        def do_POST(self):
            got["enc"] = self.headers.get("Content-Encoding")
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")

        def log_message(self, *a):
            pass
    srv = __import__("http.server").server.HTTPServer(("127.0.0.1", 0), Hd)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    code, _ = M.post_json("http://127.0.0.1:%d/api/node/logs" % srv.server_address[1], "T", {"a": 1}, {}, gz=True)
    check("[5] the log POST is gzip, said in Content-Encoding", code == 200 and got.get("enc") == "gzip"
          and json.loads(gzip.decompress(got["body"])) == {"a": 1}, got)


guarded("[5]", sec5)

# ── [6] docker: swg-sni through noded's writer ───────────────────────────────────────────────────────────────────────
print("[6] docker: swg-sni's lines")


def sec6():
    S = load("noded", {"SWG_NODED_STATE": os.path.join(TMP, "noded-pump")})
    f = os.path.join(TMP, "pump", "swg-noded.log")
    S.log_file(f, 1 << 20)
    S._sni_pump(io.BytesIO(b"W swg-sni: refused a.example\nD swg-sni: b.example -> direct\nraw line\n"))
    lines = [l.split(" ", 1)[1] for l in open(f).read().splitlines()] if os.path.exists(f) else []
    check("[6] each line reaches noded's file at its own priority (an unprefixed one at Info)",
          lines == ["W swg-sni: refused a.example", "D swg-sni: b.example -> direct", "I raw line"], lines)
    check("[6] docker starts swg-sni through the pump; bare metal keeps the inherited journal stream",
          '_pipe = NODE_KIND == "docker"' in SRC["noded"] and "target=_sni_pump" in SRC["noded"])


guarded("[6]", sec6)

# ── [7] the panel's own journal ──────────────────────────────────────────────────────────────────────────────────────
print("[7] the panel's own journal")


def sec7():
    u = SRC["update"]
    up = u.index('if should_update "bare-metal swg-panel" "$PANEL_DIR"; then')
    check("[7] update.sh gives the panel its journal inside the upgrade, before it restarts the panel",
          up < u.find("    ensure_panel_journal\n", up) < u.index("restart_panel_seeding_node_ep; then", up))
    check("[7] …and heals it on a current box with the viewer", "ensure_panel_journal; fi   # HEAL" in u)
    check("[7] the installer writes the drop-in only where the group exists; uninstall removes it; NixOS's unit has the group",
          "getent group systemd-journal" in SRC["install"] and "SWG_JOURNAL_DROPIN" in SRC["install"]
          and '"$_pdd/swg-journal.conf"' in SRC["uninstall"] and 'SupplementaryGroups = [ "systemd-journal" ];' in SRC["nix"]
          and "getent group systemd-journal" in SRC["common"])
    check("[7] docker: the renewal loop's outcome reaches the panel's file, only when that file exists (Off deleted it)",
          '[ -f "$f" ] && printf' in SRC["entry"] and SRC["entry"].count("panel_log ") >= 2)
    P = load("panel")
    fj = os.path.join(TMP, "fakejournal-panel")
    open(fj, "w").write("#!/usr/bin/env python3\nimport json, sys, time\nprint(json.dumps({'__CURSOR': 'p1', '__REALTIME_TIMESTAMP': '5',"
                        " '_SYSTEMD_UNIT': 'swg-panel-server.service', 'PRIORITY': '6', 'MESSAGE': 'hello'}), flush=True) if '-f' not in sys.argv else time.sleep(5)\n")
    os.chmod(fj, 0o755)
    rd = P.LiveReader({"panel"}, journal=lambda cur, n: P.live_journal_argv([fj], ["swg-panel-server.service"], False, cur, n), cap=200)
    try:
        out = drain(rd, 1.4)
    except Exception as e:
        out = [repr(e)]
    rd.close()
    check("[7] the panel's own copy of the reader runs: it follows a journal (every module the block uses is imported there)",
          [l[1:] for l in out] == [["panel", 6, "hello"]], out)
    P.PANEL_LOG_FILE["path"] = "/x/log/swg-panel.log"
    plan, st = P._live_panel_plan(["panel", "sub", "noded"])
    check("[7] a docker panel: its own file; sub is unavailable; a node's source is not the panel's",
          plan == {"files": [("/x/log/swg-panel.log", "panel", "ours")]} and st == {"panel": "ok", "sub": "unavailable"}, (plan, st))
    P.PANEL_LOG_FILE["path"] = None
    P.os = type("O", (), {"path": type("Q", (), {"exists": staticmethod(lambda p: True), "join": staticmethod(os.path.join)}),
                          "geteuid": staticmethod(lambda: 1000)})
    P._live_journal_access = lambda: True
    plan, st = P._live_panel_plan(["panel", "netctl"])
    a = plan["journal"](None, 10)
    P.PANEL_PLATFORM = "nixos"
    a2 = P._live_panel_plan(["panel"])[0]["journal"](None, 10)
    P._live_journal_access = lambda: False
    _p, st3 = P._live_panel_plan(["panel"])
    check("[7] bare metal reads the swg-panel namespace (merged), NixOS the main journal; no group yet → \"noaccess\"",
          a[:2] == ["journalctl", "--namespace=+swg-panel"] and "_SYSTEMD_UNIT=swg-netctl.service" in a
          and a2[0] == "journalctl" and not any(x.startswith("--namespace") for x in a2) and st3 == {"panel": "noaccess"},
          (a[:3], a2[:3], st3))


guarded("[7]", sec7)

print()
if PLANT:
    print(("CAUGHT" if FAILS else "NOT caught") + ": --plant " + PLANT)
    sys.exit(0 if FAILS else 1)
print("FAIL: %d — %s" % (len(FAILS), FAILS) if FAILS else "OK")
sys.exit(1 if FAILS else 0)
