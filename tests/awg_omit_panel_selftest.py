#!/usr/bin/env python3
"""Self-test — "an AmneziaWG field set to none" ("-"), the panel's half (docs/AWG-OMIT-AND-MESH-GEN-PLAN.md Part A, P2), driven
through REAL panel processes (temp state, scratch port, no auth; the nodes are played by POSTing snapshots).

[A] SMALL FLEETS FEEL NOTHING (§4). One API script — interface defaults saved, a node's mesh settings saved, interfaces
    created at 2.0 and 3.1, a first sync (bless), an Edit-sheet save (every cell sent, one changed), a 3.1 switch, a
    restore of a lost interface — runs against the tree before the plan (SWG_OMIT_BASE, default cba8e22) and this one,
    random and os.urandom seeded alike. nodes.json, panel-settings.json, every sync reply and every create request must be
    identical once timestamps are masked. A control runs the base twice (the comparison is deterministic), and each new path
    is PLANTED and must differ: "-" in the interface defaults, "-" in a mesh template, a partial update body (the one
    deliberate difference — it now keeps the keys it does not carry), and a take-over's partial conf (bless marks it whole).
[B] What the paths do:
    [1] the update API merges: a key sets, "-" removes, an absent key is kept
    [2] the first omission on an interface makes it WHOLE first (report under record) and is refused until the node has
        reported it; refused on a node that does not report `datapath.awg.exact`; the record then holds `awg_exact`
    [3] the rules: R1 nothing left, R2 no 3.x key left on a 3.1 interface, R3 Jc/Jmin/Jmax together, R4 a
        HeaderProtectionKey without an S, R5 S1 + 56 = S2; templates: R3 and "every field none"
    [4] the wire: the sync sends `awg_params_exact` for an `awg_exact` record and pushes a key the node still has away;
        a restore sends `exact`; a create from defaults with "-" sends a whole set marked exact, without the omitted keys
    [5] a 3.1 switch keeps the omissions (awg3_full omit); a 3.1 create from 3.1 defaults with "-" leaves them out
    [6] bless-on-first-sight marks a conf missing a 2.0 key `awg_exact`; the meta of an `awg_exact` record is the record
        alone, and carries the flag. q189 PR-3: the AmneziaWG 3.1 switch of such an adopted 1.x conf (no S3/S4) draws
        S3 and S4 — header protection needs all four, so they are never "none" there (1.8.8 drew them; 94ba204's bless
        made the switch refuse "S3, S4 cannot be none") — while its I1–I5 omissions stay
    [7] templates store "-" as written, and sanitize_awg_params never lets it through

Run: python3 tests/awg_omit_panel_selftest.py           (0 = pass)
     --perturb merge    the update replaces the record again  → RED in [1] (and the partial-body plant reads identical)
     --perturb whole    no report under the record            → RED in [2]
     --perturb wire     the sync never sends exact            → RED in [4]
     --perturb s34none  the 3.1 switch omits S1–S4 an exact record lacks  → RED in [6]
"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
BASE = os.environ.get("SWG_OMIT_BASE") or "cba8e22"

PLANTS = {
    "merge": ("[1]", "                    _m = {**_rec_u, **clean}\n                    _m = {k: _m[k] for k in AWG_FIELDS if k in _m}\n",
              "                    _m = dict(clean)\n"),
    "whole": ("[2]", "                        _rec_u = {**{k: str(v) for k, v in _ra_u.items() if k not in AWG3_FIELDS or _was3}, **_rec_u}\n",
              "                        pass\n"),
    "wire": ("[4]", "                    if extra or ov.get(\"awg_exact\"):\n", "                    if extra:\n"),
    "s34none": ("[6]", "\n                                    and k not in (\"S1\", \"S2\", \"S3\", \"S4\"))\n", ")\n"),
}
MODE = sys.argv[sys.argv.index("--perturb") + 1] if "--perturb" in sys.argv else None

FAILS = []
SECTION = [""]
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append((SECTION[0], name))

TMP = tempfile.mkdtemp(prefix="awg-omit-")
NEW = SERVER
if MODE:
    _sec, old, new = PLANTS[MODE]
    src = open(SERVER, encoding="utf-8").read()
    assert src.count(old) == 1, "plant anchor for %s matched %d times — this run would measure nothing" % (MODE, src.count(old))
    NEW = os.path.join(TMP, "swg-panel-server.new")
    open(NEW, "w", encoding="utf-8").write(src.replace(old, new))
BASEF = os.path.join(TMP, "swg-panel-server.base")
open(BASEF, "w").write(subprocess.run(["git", "-C", ROOT, "show", BASE + ":swg-panel-server"], capture_output=True,
                                      text=True, check=True).stdout)

RUNNER = os.path.join(TMP, "run.py")
open(RUNNER, "w").write(r'''
import os, random, runpy, sys
random.seed(int(os.environ["OMIT_SEED"]))
_r = random.Random(int(os.environ["OMIT_SEED"]) + 1)
os.urandom = lambda n: _r.randbytes(n)
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
''')

BASE20 = {"Jc": "4", "Jmin": "40", "Jmax": "70", "S1": "28", "S2": "94", "S3": "88", "S4": "33",
          "H1": "103509605-103509620", "H2": "1694692368-1694692383", "H3": "2553282719-2553282734",
          "H4": "3170237912-3170237927", "I1": "<b 0xc000000001><r 64><t>", "I2": "<r 24><t>", "I3": "<r 32>",
          "I4": "<b 0xc000000001><r 32><t>", "I5": "<t><r 48>"}
OLD_AWG = {k: BASE20[k] for k in ("Jc", "Jmin", "Jmax", "S1", "S2", "H1", "H2", "H3", "H4")}   # an older AmneziaWG's conf
G31 = {"module": "3.1", "fallback": "3.1", "tools": "3.1"}
PUB = "8Y1mOEM2Uv3Ez6CUfXOvsUg0dNrV4kx0mB9rp1cV3lE="
NODES_IDS = ("na", "nb", "nold")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Panel:
    def __init__(self, server, seed=7):
        self.dir = tempfile.mkdtemp(prefix="p-", dir=TMP)
        st = os.path.join(self.dir, "state"); os.makedirs(st); sd = os.path.join(self.dir, "stats"); os.makedirs(sd)
        self.nodes_path = os.path.join(st, "nodes.json")
        json.dump({n: {"id": n, "name": n, "links": {}, "ifaces": {}} for n in NODES_IDS}, open(self.nodes_path, "w"))
        open(os.path.join(st, "users.json"), "w").write("{}\n")
        fl = os.path.join(self.dir, "fleet.json")
        json.dump({"nodes_path": self.nodes_path, "roster_path": os.path.join(st, "users.json"), "stats_dir": sd}, open(fl, "w"))
        self.port = free_port()
        self.log = open(os.path.join(self.dir, "panel.log"), "w+")
        self.proc = subprocess.Popen([sys.executable, RUNNER, server], stdout=self.log, stderr=subprocess.STDOUT,
                                     env={**os.environ, "SWG_PANEL_FLEET": fl, "SWG_PANEL_WEB": ROOT, "SWG_PANEL_HOST": "127.0.0.1",
                                          "SWG_PANEL_PORT": str(self.port), "SWG_PANEL_AUTH": "", "SWG_PANEL_TLS_CERT": "",
                                          "SWG_PANEL_TLS_KEY": "", "SWG_PANEL_STATE_TTL": "0", "SWG_NO_REEXEC": "1",
                                          "OMIT_SEED": str(seed)})
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/healthz" % self.port, timeout=2); break
            except Exception:
                if self.proc.poll() is not None:
                    sys.exit("panel exited: " + open(self.log.name).read()[-2000:])
                time.sleep(0.1)
        self.tok = {n: self.req("/api/nodes/rotate", {"id": n})[1]["data"]["token"] for n in NODES_IDS}
        self.settings_path = os.path.join(st, "panel-settings.json")

    def req(self, path, data=None, token=None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                   data=json.dumps(data).encode() if data is not None else None,
                                   headers={"Content-Type": "application/json",
                                            **({"Authorization": "Bearer " + token} if token else {})})
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                raw = resp.read(); code = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read(); code = e.code
        try:
            return code, json.loads(raw or b"{}")
        except Exception:
            return code, {"raw": raw[:200]}

    def nodes(self):
        return json.load(open(self.nodes_path))

    def put(self, nid, iface, rec):
        n = self.nodes(); n[nid].setdefault("ifaces", {})[iface] = rec
        with open(self.nodes_path + ".tmp", "w") as f:
            json.dump(n, f)
        os.replace(self.nodes_path + ".tmp", self.nodes_path)

    def ov(self, nid, iface):
        return (self.nodes()[nid].get("ifaces") or {}).get(iface) or {}

    def sync(self, nid, ifaces, exact=True, gen=True):
        """ifaces: {name: reported awg params (None = no params)}"""
        s = {"hostname": nid, "generated_at": int(time.time()), "noded_version": "t", "interfaces": {}}
        for i, (ifn, awg) in enumerate(sorted(ifaces.items())):
            s["interfaces"][ifn] = {"peers": [], "meta": {"public_key": PUB, "listen_port": 51820 + i, "mtu": 1280,
                                                        "subnet": "10.6%d.0.0/24" % i, "address": "10.6%d.0.1/24" % i,
                                                        **({"awg_params": awg} if awg else {}), "tool": "awg"}}
        if gen:
            s["datapath"] = {"awg": {"gen": dict(G31), **({"exact": 1} if exact else {})}}
        code, r = self.req("/api/node/sync", {"snapshot": s}, self.tok[nid])
        assert code == 200, (code, r)
        return r

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:
            self.proc.kill()


def mask(o, port=None):
    """Timestamps and run-unique values (the scratch port) masked, so two runs compare. Also the sync reply's
    `smart.p2p`, the node's torrent policy: its default changed ON PURPOSE on 2026-10-08 (block when nothing is saved —
    the base sent None for a node with an interface record lacking torrents), which is not this plan's subject; the
    policy's own gate is tests/p2p_policy_panel_selftest.py."""
    if isinstance(o, dict):
        return {k: ("T" if k in ("created", "at", "generated_at", "seen", "last_seen", "ts", "panel_now", "token", "token_hash",
                                 "token_sha", "_seen") or (k == "p2p" and "entries" in o) else mask(v, port)) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [mask(v, port) for v in o]
    if isinstance(o, (int, float)) and not isinstance(o, bool) and (o > 1.7e9 or (port and o == port)):
        return "T"
    if isinstance(o, str) and port and str(port) in o:
        return o.replace(str(port), "PORT")
    return o


DEFAULTS = {"dns": "1.1.1.1", "mtu": 1280, "keepalive": 25, "awg_params": {"Jc": "5", "Jmin": "50", "Jmax": "80"},
            "awg3_params": {"ContentPaddingAddition": "20-40"}, "awg_gen": "2.0", "reach": "user"}


def script(p, plant=None):
    """The differential script. Returns everything a node or a browser is handed, plus the stored files."""
    out = []
    idf = dict(DEFAULTS)
    if plant == "defaults-omit":
        idf = {**DEFAULTS, "awg_params": {**DEFAULTS["awg_params"], "I2": "-"}}
    mawg = {"S3": "-"} if plant == "mesh-omit" else {}
    out.append(p.req("/api/panel/settings", {"interface_defaults": idf, "mesh_awg": mawg, "mesh_mode": "auto",
                                             "mesh_awg_gen": "2.0"}))
    out.append(p.req("/api/nodes/update", {"id": "na", "mesh_subnet": "", "mesh_port": "",   # what the SPA's node save sends
                                           "mesh_prefix": ""}))
    p.sync("na", {}); p.sync("nb", {})
    out.append(p.req("/api/iface/create", {"node": "na", "iface": "awg0", "subnet": "10.60.0.0/24", "listen_port": 51820}))
    out.append(p.req("/api/iface/create", {"node": "na", "iface": "awg1", "subnet": "10.61.0.0/24", "listen_port": 51821,
                                           "awg_gen": "3.1"}))
    out.append(p.nodes()["na"].get("create"))
    rep0 = {**BASE20, **(p.ov("na", "awg0").get("awg_params") or {})}
    rep1 = dict(p.ov("na", "awg1").get("awg_params") or {})
    out.append(p.sync("na", {"awg0": rep0, "awg1": rep1}))
    rep2 = OLD_AWG if plant == "takeover" else dict(BASE20)
    out.append(p.sync("nb", {"wg5": rep2}))                       # a reported interface the panel never made: bless
    out.append(p.sync("nb", {"wg5": rep2}))
    body = {**rep0, "Jc": "6"} if plant != "partial" else {"Jc": "6"}
    out.append(p.req("/api/iface/update", {"node": "na", "iface": "awg0", "awg_params": body}))
    out.append(p.sync("na", {"awg0": rep0, "awg1": rep1}))
    out.append(p.req("/api/iface/update", {"node": "na", "iface": "awg0", "awg_gen": "3.1"}))
    out.append(p.sync("na", {"awg0": rep0, "awg1": rep1}))
    out.append(p.sync("na", {"awg1": rep1}))                       # awg0 lost → a restore
    out.append(p.req("/api/iface/recreate", {"node": "na", "iface": "awg0"}))
    out.append(p.nodes()["na"].get("create"))
    out.append(p.nodes())
    out.append(json.load(open(p.settings_path)))
    return mask(out, p.port)


def _path(x, y, at=""):
    """The first JSON path where x and y disagree, with both values."""
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x or k not in y:
                return at + "/" + str(k), x.get(k, "<absent>"), y.get(k, "<absent>")
            r = _path(x[k], y[k], at + "/" + str(k))
            if r:
                return r
        return None
    if isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (u, v) in enumerate(zip(x, y)):
            r = _path(u, v, "%s[%d]" % (at, i))
            if r:
                return r
        return None
    return None if x == y else (at, str(x)[:200], str(y)[:200])


def differ(a, b):
    """Where two script outputs first disagree (step, JSON path, both values), or None."""
    return _path(a, b)


try:
    SECTION[0] = "[A]"
    print("[A] no \"-\" anywhere ⇒ what the base (%s) did, byte for byte" % BASE)
    runs = {}
    for name, srv, plant in (("base", BASEF, None), ("base2", BASEF, None), ("new", NEW, None),
                             ("base-defaults-omit", BASEF, "defaults-omit"), ("new-defaults-omit", NEW, "defaults-omit"),
                             ("base-mesh-omit", BASEF, "mesh-omit"), ("new-mesh-omit", NEW, "mesh-omit"),
                             ("base-partial", BASEF, "partial"), ("new-partial", NEW, "partial"),
                             ("base-takeover", BASEF, "takeover"), ("new-takeover", NEW, "takeover")):
        p = Panel(srv)
        try:
            runs[name] = script(p, plant)
        finally:
            p.close()
    check("control: the base twice is identical (the comparison is deterministic)", differ(runs["base"], runs["base2"]) is None,
          differ(runs["base"], runs["base2"]))
    check("no \"-\": stored state, sync replies, create requests identical to the base", differ(runs["base"], runs["new"]) is None,
          differ(runs["base"], runs["new"]))
    for pl in ("defaults-omit", "mesh-omit", "partial", "takeover"):
        check("plant %s: the new path runs, and the comparison sees it" % pl, differ(runs["base-" + pl], runs["new-" + pl]) is not None)

    SECTION[0] = "[B]"
    p = Panel(NEW)
    try:
        p.sync("na", {}); p.sync("nb", {}); p.sync("nold", {}, exact=False)
        SECTION[0] = "[1]"
        print("\n[1] the update API merges")
        p.put("na", "awg0", {"awg_params": dict(BASE20)})
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg0", "awg_params": {"Jc": "5", "Jmin": "", "S3": ""}})
        a = p.ov("na", "awg0").get("awg_params") or {}
        check("a partial body sets Jc and keeps every key it does not carry (blank = keep)",
              code == 200 and a.get("Jc") == "5" and all(a.get(k) == BASE20[k] for k in BASE20 if k != "Jc"), (code, r, a))
        check("…and no awg_exact without an omission", "awg_exact" not in p.ov("na", "awg0"))

        SECTION[0] = "[2]"
        print("\n[2] the first omission makes the set whole, and needs the node")
        p.put("na", "awg0", {"awg_params": {"Jc": "5", "Jmin": "50", "Jmax": "80"}})      # partial, as a create from defaults leaves it
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg0", "awg_params": {"I5": "-"}})
        check("refused while the node has not reported the interface", code == 400 and "wait for the node" in r.get("error", ""), (code, r))
        p.sync("na", {"awg0": {**BASE20, "Jc": "5", "Jmin": "50", "Jmax": "80"}})
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg0", "awg_params": {"I5": "-"}})
        o = p.ov("na", "awg0"); a = o.get("awg_params") or {}
        check("accepted once reported: the record holds the device's S/H (report under record) and Jc 5, no I5",
              code == 200 and a.get("S1") == BASE20["S1"] and a.get("H4") == BASE20["H4"] and a.get("Jc") == "5"
              and "I5" not in a and len(a) == 15, (code, r, a))
        check("…and awg_exact", o.get("awg_exact") is True, o)
        p.put("nold", "awg0", {"awg_params": dict(BASE20)})
        p.sync("nold", {"awg0": dict(BASE20)}, exact=False)
        code, r = p.req("/api/iface/update", {"node": "nold", "iface": "awg0", "awg_params": {"I5": "-"}})
        check("a node without datapath.awg.exact: refused, naming it", code == 400 and "nold cannot hold an empty" in r.get("error", ""), (code, r))
        check("…and its record untouched", p.ov("nold", "awg0").get("awg_params") == BASE20)

        SECTION[0] = "[3]"
        print("\n[3] the rules")
        def upd(body, iface="awg0", nid="na"):
            return p.req("/api/iface/update", {"node": nid, "iface": iface, "awg_params": body})
        p.put("na", "awg0", {"awg_params": dict(BASE20), "awg_exact": True})
        code, r = upd({k: "-" for k in BASE20})
        check("R1 every field none → refused, WireGuard suggested", code == 400 and "WireGuard" in r.get("error", ""), (code, r))
        code, r = upd({"Jc": "-"})
        check("R3 Jc alone → refused", code == 400 and "Jc, Jmin and Jmax" in r.get("error", ""), (code, r))
        code, r = upd({"Jc": "-", "Jmin": "-", "Jmax": "-"})
        check("R3 all three → accepted", code == 200 and not any(k in (p.ov("na", "awg0").get("awg_params") or {}) for k in ("Jc", "Jmin", "Jmax")), (code, r))
        code, r = upd({"S2": "84", "S1": "28", "I5": "-"})
        check("R5 S2 = S1 + 56 in a save that removes a field → refused", code == 400 and "S1 + 56" in r.get("error", ""), (code, r))
        H = "ZPx7sT8PpJ3aUVTMYCWgSVhdLbq0uVpO6hZe3mO2yJ0="
        S31 = {"HeaderProtectionKey": H, "RandomTrailers": "1", "ContentPaddingAddition": "10-100"}
        p.put("na", "awg9", {"awg_params": {**BASE20, **S31}, "awg_exact": True})
        p.sync("na", {"awg9": {**BASE20, **S31}})
        code, r = upd({"S3": "-"}, "awg9")
        check("R4 S3 none beside a HeaderProtectionKey → refused, naming S3", code == 400 and "S3" in r.get("error", "")
              and "header protection" in r.get("error", ""), (code, r))
        code, r = upd({"HeaderProtectionKey": "-", "RandomTrailers": "-", "ContentPaddingAddition": "-"}, "awg9")
        check("R2 every 3.x key none on a 3.1 interface → refused (switch to 2.0)", code == 400 and "2.0" in r.get("error", ""), (code, r))
        code, r = upd({"HeaderProtectionKey": "-", "S3": "-"}, "awg9")
        check("…while the key itself may be none, and then S3 may be too", code == 200, (code, r))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {"Jmin": "-"}}})
        check("template R3: Jmin alone none → refused", code == 400 and "Jc, Jmin and Jmax" in r.get("error", ""), (code, r))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {k: "-" for k in BASE20}}})
        check("template: every field none → refused", code == 400 and "every AmneziaWG field is none" in r.get("error", ""), (code, r))
        code, r = p.req("/api/panel/settings", {"mesh_awg": {"S1": "-"}, "mesh_awg_gen": "3.1"})
        check("mesh R4: type 3.1 with S1 none → refused", code == 400 and "S1" in r.get("error", ""), (code, r))
        # review fixes: an inheriting node's own template is judged at the panel-wide door, and the node door only on a change
        # the panel door judges ITS OWN template, and only when it changes: a node in conflict (it inherits 3.1 over an S set
        # to none) gets its links at 2.0 with the reason (mesh_gen_selftest), and never blocks a Settings save (code review 2)
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg": {"S3": "-"}})
        code2, r2 = p.req("/api/panel/settings", {"mesh_awg": {}, "mesh_awg_gen": "3.1"})
        check("panel-wide type 3.1 while a link that inherits it omits S3: accepted (that link falls back, said on its card)",
              code == 200 and code2 == 200, (code, r, code2, r2))
        code, r = p.req("/api/panel/settings", {"mesh_awg": {}, "mesh_awg_gen": "3.1", "top_talkers": 12})
        check("…and an unrelated Settings save with that link still in conflict goes through", code == 200, (code, r))
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "dial_endpoint": ""})
        check("…and so does that link's unrelated save", code == 200 and r["data"]["relinked"] is False, (code, r))
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg_gen": "3.1"})
        check("…but choosing 3.1 for that link itself → refused (R4 at the link door)", code == 400 and "S3" in r.get("error", ""), (code, r))
        p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg": {}}); p.req("/api/panel/settings", {"mesh_awg_gen": "2.0"})
        p.put("na", "awg8", {"awg_params": {"Jc": "4", "S1": "28", "S2": "84"}, "awg_exact": True})   # a foreign conf: Jc alone, S2 = S1 + 56
        p.sync("na", {"awg8": {"Jc": "4", "S1": "28", "S2": "84"}})
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg8", "dns": "9.9.9.9",
                                              "awg_params": {"Jc": "4", "S1": "28", "S2": "84"}})
        check("a whole set blessed from a foreign conf that breaks the rules keeps every edit that removes nothing", code == 200, (code, r))
        p.put("na", "awg9b", {"awg_params": {"HeaderProtectionKey": H, "RandomTrailers": "1"}, "awg_exact": True})
        p.sync("na", {"awg9b": {"HeaderProtectionKey": H, "RandomTrailers": "1"}})
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg9b", "awg_gen": "2.0"})
        check("a 2.0 switch that would leave a whole set with no field → refused (R1), the record kept",
              code == 400 and "WireGuard" in r.get("error", "") and p.ov("na", "awg9b").get("awg_exact") is True, (code, r))
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg8", "awg_params": {}})
        check("an awg_params: {} body clears the set — and the flag with it", code == 200 and "awg_exact" not in p.ov("na", "awg8")
              and "awg_params" not in p.ov("na", "awg8"), p.ov("na", "awg8"))
        p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg3_params": {"ContentPaddingAddition": "-"}}})
        code, r = p.req("/api/iface/create", {"node": "nold", "iface": "wg9", "subnet": "10.69.0.0/24", "listen_port": 51835,
                                              "protocol": "wg", "awg_gen": "3.1"})
        check("a WireGuard create asked for 3.1 gets the plain-WireGuard refusal, not the node-capability one",
              code == 400 and "plain WireGuard" in r.get("error", ""), (code, r))
        p.req("/api/panel/settings", {"interface_defaults": DEFAULTS})

        SECTION[0] = "[4]"
        print("\n[4] the wire")
        p.put("na", "awg0", {"awg_params": {k: v for k, v in BASE20.items() if k != "S3"}, "awg_exact": True})
        r = p.sync("na", {"awg0": dict(BASE20)})
        d = (r.get("desired_ifaces") or {}).get("awg0") or {}
        check("the device still has S3: pushed, marked exact, without S3", d.get("awg_params_exact") is True
              and "S3" not in (d.get("awg_params") or {}) and d.get("awg_params"), d)
        r = p.sync("na", {"awg0": {**{k: v for k, v in BASE20.items() if k != "S3"}, "Jc": "9"}})
        d = (r.get("desired_ifaces") or {}).get("awg0") or {}
        check("a value the node has wrong (no extra key) on an awg_exact record: pushed marked exact too — the node must "
              "neither keep nor invent a key", d.get("awg_params_exact") is True and (d.get("awg_params") or {}).get("Jc") == "4", d)
        r = p.sync("na", {"awg0": {k: v for k, v in BASE20.items() if k != "S3"}})
        d = (r.get("desired_ifaces") or {}).get("awg0") or {}
        check("once gone: nothing to push", "awg_params" not in d, d)
        o = p.nodes()["na"]["ifaces"]["awg0"]
        check("…and it reads synced", (o.get("_synced") or {}).get("awg_params") is not None, o.get("_synced"))
        p.sync("na", {})                                           # awg0 lost
        code, r = p.req("/api/iface/recreate", {"node": "na", "iface": "awg0"})
        cr = (p.nodes()["na"].get("create") or {}).get("awg0") or {}
        check("a restore sends the whole set marked exact", code == 200 and cr.get("awg_params_exact") is True
              and "S3" not in (cr.get("awg_params") or {}), (code, r, cr))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {"Jc": "5", "Jmin": "50",
                                                                                                  "Jmax": "80", "I3": "-", "I4": "-"}}})
        check("interface defaults with \"-\" saved", code == 200, (code, r))
        code, r = p.req("/api/iface/create", {"node": "nb", "iface": "awg4", "subnet": "10.64.0.0/24", "listen_port": 51830})
        cr = (p.nodes()["nb"].get("create") or {}).get("awg4") or {}
        a = cr.get("awg_params") or {}
        check("a create from them: a whole set (S/H drawn by the panel), marked exact, no I3/I4",
              code == 200 and cr.get("awg_params_exact") is True and a.get("Jc") == "5" and "S1" in a and "H4" in a
              and "I3" not in a and "I4" not in a and len(a) == 14, (code, cr))
        check("…stored whole with awg_exact", p.ov("nb", "awg4").get("awg_exact") is True and p.ov("nb", "awg4").get("awg_params") == a)
        code, r = p.req("/api/iface/create", {"node": "nold", "iface": "awg4", "subnet": "10.65.0.0/24", "listen_port": 51831})
        check("…refused on a node without datapath.awg.exact", code == 400 and "cannot hold an empty" in r.get("error", ""), (code, r))
        code, r = p.req("/api/iface/create", {"node": "nb", "iface": "wg4", "subnet": "10.66.0.0/24", "listen_port": 51832, "protocol": "wg"})
        cr = (p.nodes()["nb"].get("create") or {}).get("wg4") or {}
        check("control: a WireGuard create ignores the AWG defaults", code == 200 and not cr.get("awg_params") and not cr.get("awg_params_exact"), cr)

        SECTION[0] = "[5]"
        print("\n[5] 3.1 keeps the omissions")
        p.put("na", "awg5", {"awg_params": {k: v for k, v in BASE20.items() if k not in ("I1", "I2")}, "awg_exact": True})
        p.sync("na", {"awg5": {k: v for k, v in BASE20.items() if k not in ("I1", "I2")}})
        code, r = p.req("/api/iface/update", {"node": "na", "iface": "awg5", "awg_gen": "3.1"})
        a = p.ov("na", "awg5").get("awg_params") or {}
        check("the 3.1 switch of a whole record leaves I1/I2 out (no refill from the generator or the report)",
              code == 200 and a.get("HeaderProtectionKey") and "I1" not in a and "I2" not in a, (code, r, a))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {"Jc": "5", "Jmin": "50", "Jmax": "80"},
                                                                       "awg3_params": {"ContentPaddingAddition": "-", "KeepaliveTimeout": "-"}}})
        check("3.1 defaults with \"-\" saved", code == 200 and (json.load(open(p.settings_path))["interface_defaults"].get("awg3_params") or {})
              == {"ContentPaddingAddition": "-", "KeepaliveTimeout": "-"}, (code, r))
        code, r = p.req("/api/iface/create", {"node": "nb", "iface": "awg6", "subnet": "10.67.0.0/24", "listen_port": 51833, "awg_gen": "3.1"})
        cr = (p.nodes()["nb"].get("create") or {}).get("awg6") or {}
        a = cr.get("awg_params") or {}
        check("a 3.1 create from them: no ContentPaddingAddition, no KeepaliveTimeout, the rest of the 3.1 set, exact",
              code == 200 and a.get("HeaderProtectionKey") and a.get("RandomTrailers") == "1" and "ContentPaddingAddition" not in a
              and "KeepaliveTimeout" not in a and a.get("RekeyAfterTime") and cr.get("awg_params_exact") is True, (code, cr))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {"S2": "-"}, "awg3_params": {}}})
        code2, r2 = p.req("/api/iface/create", {"node": "nb", "iface": "awg7", "subnet": "10.68.0.0/24", "listen_port": 51834, "awg_gen": "3.1"})
        check("a 3.1 create from defaults with S2 none → refused (R4), naming S2", code == 200 and code2 == 400 and "S2" in r2.get("error", ""), (code, r, code2, r2))
        p.req("/api/panel/settings", {"interface_defaults": DEFAULTS})

        SECTION[0] = "[6]"
        print("\n[6] bless, and the meta")
        p.sync("nb", {"wg7": dict(OLD_AWG)})
        o = p.ov("nb", "wg7")
        check("a take-over's conf without S3/S4/I is blessed WHOLE (awg_exact)", o.get("awg_exact") is True and o.get("awg_params") == OLD_AWG, o)
        code, r = p.req("/api/iface/update", {"node": "nb", "iface": "wg7", "awg_gen": "3.1"})
        a = p.ov("nb", "wg7").get("awg_params") or {}
        check("PR-3: its AmneziaWG 3.1 switch is taken — S3 and S4 drawn (12 or more), its own Jc…S2/H kept, I1–I5 still out",
              code == 200 and a.get("HeaderProtectionKey") and all(k in a and int(a[k]) >= 12 for k in ("S3", "S4"))
              and all(a.get(k) == v for k, v in OLD_AWG.items()) and not any(k in a for k in ("I1", "I2", "I3", "I4", "I5")),
              (code, r.get("error"), a))
        p.sync("nb", {"wg8": dict(BASE20)})
        check("control: a full conf is blessed without the flag", "awg_exact" not in p.ov("nb", "wg8"), p.ov("nb", "wg8"))
        p.put("na", "awg0", {"awg_params": {k: v for k, v in BASE20.items() if k != "S3"}, "awg_exact": True})
        p.sync("na", {"awg0": dict(BASE20)})                    # the device still has S3
        code, st = p.req("/api/state")
        m = (((st.get("data") or {}).get("describe") or {}).get("na") or {}).get("awg0") or {}
        m = m.get("meta") or m
        check("the meta of an awg_exact record is the record alone (S3 does not come back through the report)",
              "S3" not in (m.get("awg_params") or {}) and (m.get("awg_params") or {}).get("S4") == BASE20["S4"], m.get("awg_params"))
        check("…and carries awg_exact", m.get("awg_exact") is True, sorted(m)[:40])

        SECTION[0] = "[7]"
        print("\n[7] templates keep \"-\"; records never hold it")
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg_params": {"Jc": "5", "Jmin": "50", "Jmax": "80", "S3": "-"}},
                                                "mesh_awg": {"I1": "-", "S4": "20"}})
        ps = json.load(open(p.settings_path))
        check("the interface defaults store \"-\" as written", (ps["interface_defaults"].get("awg_params") or {}).get("S3") == "-", ps["interface_defaults"])
        check("the mesh template stores \"-\" as written", (ps.get("mesh_awg") or {}) == {"S4": "20", "I1": "-"}, ps.get("mesh_awg"))
        lt = lambda: (((p.nodes()["na"].get("mesh_link") or {}).get("nb") or {}).get("awg") or {})   # the pair's own params, on its anchor
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg": {"I2": "-", "Jc": "3", "Jmin": "30", "Jmax": "60"}})
        check("a link's own params store \"-\" (on the pair's anchor, from either end)", code == 200 and lt().get("I2") == "-", (code, r, lt()))
        code, r = p.req("/api/nodes/update", {"id": "nb", "mesh_awg": {"Jc": "9"}})
        check("a node's own mesh_awg is no longer a setting: ignored, nothing stored", code == 200 and "mesh_awg" not in p.nodes()["nb"],
              p.nodes()["nb"].get("mesh_awg"))
        blob = json.dumps({n: {i: r.get("awg_params") for i, r in (v.get("ifaces") or {}).items()} for n, v in p.nodes().items()})
        # the mesh templates' 3.1 six (plan §8 round 11): kept, checked, and a node's change re-provisions its links
        code, r = p.req("/api/panel/settings", {"mesh_awg": {"Jc": "4", "Jmin": "40", "Jmax": "70", "RekeyTimeout": "4-8", "ContentPaddingAddition": "-"}})
        ps = json.load(open(p.settings_path))
        check("the panel's mesh template keeps its 3.1 fields, \"-\" included", code == 200
              and ps.get("mesh_awg", {}).get("RekeyTimeout") == "4-8" and ps["mesh_awg"].get("ContentPaddingAddition") == "-", ps.get("mesh_awg"))
        code, r = p.req("/api/panel/settings", {"mesh_awg": {"RekeyAfterTime": "170-180"}})
        check("…and refuses 3.1 timings that cross", code == 400 and "RejectAfterTime" in r.get("error", ""), (code, r))
        if0 = ((p.nodes()["na"].get("links") or {}).get("nb") or {}).get("iface")
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {"KeepaliveTimeout": "6-12"}})
        check("a link's 3.1 field: stored, and that link rebuilt under a new name", code == 200 and r["data"]["relinked"] is True
              and lt().get("KeepaliveTimeout") == "6-12" and ((p.nodes()["na"].get("links") or {}).get("nb") or {}).get("iface") != if0,
              (code, r, lt()))
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg": {"KeepaliveTimeout": " 6-12 "}})
        check("…the same params again (from the other end, spaced): no rebuild", code == 200 and r["data"]["relinked"] is False, (code, r))
        p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg3_params": {"RekeyAfterTime": "60-80", "RejectAfterTime": "110-180"}}})
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {"RekeyAfterTime": "100-128"}})
        check("a link's 3.1 field that passes alone but crosses with the interface defaults below it → refused (code review 1)",
              code == 400 and "RejectAfterTime" in r.get("error", ""), (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {"Jmin": "-"}})
        check("…and a link's params that break R3 → refused", code == 400 and "Jc, Jmin and Jmax" in r.get("error", ""), (code, r))
        # code review of round 13: the 3.1 timings are judged only for a 3.1 link — leaving 3.1 never waits on them
        p.req("/api/panel/settings", {"interface_defaults": DEFAULTS})
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {"RekeyAfterTime": "100-120"}})
        check("(setup) a link's RekeyAfterTime that fits", code == 200, (code, r))
        code, r = p.req("/api/panel/settings", {"interface_defaults": {**DEFAULTS, "awg3_params": {"RekeyAfterTime": "60-80", "RejectAfterTime": "110-180"}}})
        check("(setup) defaults that fit alone, but cross the link's own RekeyAfterTime", code == 200, (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "wg"})
        check("a link whose 3.1 timings cross (after the defaults below changed) can still be switched to WG", code == 200, (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "3.1"})
        check("…but not to 3.1", code == 400 and "RejectAfterTime" in r.get("error", ""), (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {"RekeyAfterTime": "100-120", "Jc": "7", "Jmin": "50", "Jmax": "80"}})
        check("…and a Jc edit on it is not held up by those 3.1 values either", code == 200, (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "", "mesh_awg": {"Jc": "5", "Jmin": "50", "Jmax": "80"}})
        _d = p.req("/api/events?limit=5")[1].get("data")
        evs = [e for e in (_d if isinstance(_d, list) else (_d or {}).get("events", [])) if e.get("verb") == "Re-provisioned mesh link"]
        check("a save that changes the type AND the params says both in its event", code == 200 and evs
              and "AWG params changed" in (evs[0].get("detail") or ""), (code, r, evs[:1]))
        # …and R4 is judged against what the link is BUILT from: its template over the fleet's
        p.req("/api/panel/settings", {"interface_defaults": DEFAULTS, "mesh_awg": {"S1": "-"}})
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "3.1", "mesh_awg": {"Jc": "5", "Jmin": "50", "Jmax": "80"}})
        check("type 3.1 on a link whose own params are fine but which inherits S1 = none from the fleet → refused (code review)",
              code == 400 and "S1" in r.get("error", ""), (code, r))
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "3.1", "mesh_awg": {"S1": "30"}})
        check("…and accepted once the link gives S1 a value of its own", code == 200, (code, r))
        p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": ""}); p.req("/api/panel/settings", {"mesh_awg": {}})
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": {}})
        check("{} clears a link's own params (back to the fleet's), rebuilt", code == 200 and r["data"]["relinked"] is True
              and "mesh_link" not in p.nodes()["na"], (code, r, p.nodes()["na"].get("mesh_link")))
        p.req("/api/panel/settings", {"mesh_awg": {}})
        # a LINK's own type (plan §8 round 12), through the door its sheet uses
        lnk = lambda a, b: (p.nodes()[a].get("links") or {}).get(b) or {}
        old_if = lnk("na", "nb").get("iface")
        p.req("/api/connection/update", {"node": "nb", "peer": "na", "dial_endpoint": "203.0.113.9"})
        code, r = p.req("/api/connection/update", {"node": "nb", "peer": "na", "mesh_awg_gen": "wg"})
        nn = p.nodes()
        check("a link's type set from either end: stored on the pair's anchor (na), the link rebuilt as WG on both ends",
              code == 200 and r.get("data", {}).get("relinked") is True and ((nn["na"].get("mesh_link") or {}).get("nb") or {}).get("type") == "wg"
              and lnk("na", "nb").get("proto") == "wg" and lnk("nb", "na").get("proto") == "wg", (code, r, nn["na"].get("mesh_link")))
        check("…under a new interface name, the old one staged for deletion on both ends",
              lnk("na", "nb").get("iface") != old_if and old_if in (nn["na"].get("delete") or {}), (old_if, lnk("na", "nb").get("iface")))
        check("…keeping the link's own settings (its dial address)", lnk("nb", "na").get("dial_endpoint") == "203.0.113.9", lnk("nb", "na"))
        code, st = p.req("/api/state")
        mp = next((x for x in st["data"]["nodes"] if x["id"] == "nb"), {}).get("mesh_peers") or []
        check("/api/state names the link's type and its own choice", any(x.get("peer") == "na" and x.get("type") == "wg"
              and x.get("type_set") == "wg" for x in mp), mp)
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "wg"})
        check("the same type again: no rebuild", code == 200 and r.get("data", {}).get("relinked") is False, r)
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": ""})
        check("back to the fleet's default: the choice removed, the link rebuilt as AmneziaWG",
              code == 200 and "mesh_link" not in p.nodes()["na"] and "proto" not in lnk("na", "nb"), (code, r, lnk("na", "nb")))
        _codes = [p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg": v})[0] for v in (["Jc", "5"], [], "", 0, False)]
        check("a mesh_awg that is not an object (a list, [], \"\", 0, false) is refused, never a silent clear", _codes == [400] * 5, _codes)
        code, r = p.req("/api/connection/update", {"node": "na", "peer": "nb", "mesh_awg_gen": "4.0"})
        check("an unknown type is refused", code == 400, (code, r))
        check("no record holds \"-\"", '"-"' not in blob)
        check("no create request holds \"-\"", '"-"' not in json.dumps({n: v.get("create") for n, v in p.nodes().items()}))
    finally:
        p.close()
finally:
    pass

print()
if MODE:
    want = PLANTS[MODE][0]
    red = sorted({s for s, _ in FAILS})
    ok = want in red and set(red) <= {want, "[A]"}
    print(("PERTURB OK — %s went red on %s" if ok else "PERTURB FAILED — %s: red sections %s, wanted %s")
          % ((MODE, red) if ok else (MODE, red, want)))
    sys.exit(0 if ok else 1)
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join("%s %s" % f for f in FAILS))); sys.exit(1)
print("ALL PASS"); sys.exit(0)
