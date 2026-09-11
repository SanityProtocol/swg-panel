"""Self-test — AN EXIT ON A NODE TOO OLD TO HAVE EXITS MUST SAY SO, not spin.

The exits feature is newer than `main`. A node running `main`'s swg-noded has no exit code at all: it
reports no `exits` key, so the panel's live map for it is empty and always will be. Every verdict in
`exitHealth` then resolved to PROGRESS:

    imported exit  ->  "Waiting for the node to set this up…"          busy spinner, for ever
    adopted exit   ->  "This node hasn't reported a device by this name."   about a device that is up

MEASURED on hel-flux, rolled back to `main`'s swg-noded against a `1.8.6-beta` panel, with the node record
taken straight off `/api/state`. That skew is the NORMAL one: the panel is what an operator updates first,
and `update.sh` defaults to `SWG_REF:-main`, so a node stays on `main` until it is told otherwise.

⚠️ CAPABILITY, NOT VERSION. The panel decides this from the ABSENCE of the `exits` key, because a node that
runs the exits code reports it on every pass, empty list included. A version compare would decide it from a
string — and this very fleet has carried a node stamped `1.8.6-beta+091ac8e-ksni` while running a binary
newer than that commit.

⚠️ THIS DRIVES BOTH READERS AND THE WIRE BETWEEN THEM. The fact is derived in `api("GET", "/api/state")` and
consumed in `js/routing.js`; each end is defensible alone and a fixture of either would stay green while the
field never travelled. So the panel is asked for a real node record and THAT RECORD, unedited, is handed to
the real `exitHealth` in a node process.

Run: python3 tests/exit_node_too_old_selftest.py      (0 = pass)
     --perturb-panel   panel stops deriving the flag  -> the old node must go back to spinning
     --perturb-spa     SPA stops reading it           -> same, from the other end
"""
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PANEL = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PP = "--perturb-panel" in sys.argv
PS = "--perturb-spa" in sys.argv

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:220]) if detail and not ok else ""))
    if not ok:
        FAILS.append(name)

SRC = open(PANEL, encoding="utf-8").read()
_DERIVE = '            _x_unsup = bool(snap) and not isinstance(snap.get("exits"), list)\n'
# ⚠️ ASSERT THE ANCHOR. A replacement that matches nothing leaves the tree intact and the perturbation run
# reads as a clean PASS while measuring code it never touched.
assert SRC.count(_DERIVE) == 1, "anchor missing — this run would FALSE-PASS:\n" + _DERIVE
if PP:
    SRC = SRC.replace(_DERIVE, '            _x_unsup = False\n')

panel = PANEL
if PP:
    _fd, panel = tempfile.mkstemp(suffix=".py", prefix="xtoo-", dir=HERE)
    os.write(_fd, SRC.encode()); os.close(_fd)
_l = importlib.machinery.SourceFileLoader("swgpanel", panel)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel", _l))
try:
    _l.exec_module(P)
except SystemExit:
    pass
if PP:
    os.unlink(panel)
P.ev_append = lambda *a, **k: None

EXITS = [{"id": "aabbccdd", "label": "imported one", "producer": "imported", "provider": "warp",
          "device": "wgx-aabbccdd", "enabled": True, "killswitch": False, "cfg_sig": "0123456789ab"},
         {"id": "11223344", "label": "adopted one", "producer": "adopted", "device": "lab0",
          "enabled": True, "killswitch": False, "gw": "10.99.0.1"}]

# The three node shapes that matter, and they are NOT interchangeable:
#   old    a node that IS reporting, with no `exits` key at all           -> too old
#   new    a node reporting `exits: []` (it has the feature, nothing up)  -> ordinary "creating"
#   never  a node that has never synced (no snapshot)                     -> ordinary "creating"
SNAPS = {"old":   {"hostname": "old", "interfaces": {}, "generated_at": 1789000000},
         "new":   {"hostname": "new", "interfaces": {}, "generated_at": 1789000000, "exits": []},
         "never": None}


def state_nodes():
    td = tempfile.mkdtemp(prefix="xtoo-")
    np_, rp_ = (os.path.join(td, f) for f in ("nodes.json", "users.json"))
    json.dump({k: {"id": k, "name": k, "links": {}, "ifaces": {},
                   "exits": json.loads(json.dumps(EXITS))} for k in SNAPS}, open(np_, "w"))
    open(rp_, "w").write("{}\n")
    deps = {"fleet": {}, "nodes_path": np_, "roster_path": rp_, "panel_settings": {},
            "panel_settings_path": os.path.join(td, "ps.json"),
            "node_snaps": {k: v for k, v in SNAPS.items() if v is not None}}
    # /api/state reads a couple of things off the live Handler (the request-scoped deps a real server
    # sets up); point them at this fixture's own dict rather than at nothing.
    P.Handler.deps = deps
    st, resp = P.api("GET", "/api/state", "", {}, deps)
    assert st == 200, (st, resp)
    return {n["id"]: n for n in ((resp.get("data") or {}).get("nodes") or [])}


print("[1] the panel derives it from the WIRE, not from a version string")
N = state_nodes()
check("a node reporting no `exits` key at all reads as too old",
      N["old"].get("exits_unsupported") is True, N["old"].get("exits_unsupported"))
check("…a node reporting `exits: []` does NOT (it has the feature, nothing is up yet)",
      N["new"].get("exits_unsupported") is False, N["new"].get("exits_unsupported"))
check("⚠️ …and neither does a node that has simply never synced — that one is still 'creating'",
      N["never"].get("exits_unsupported") is False, N["never"].get("exits_unsupported"))

print("\n[2] the flag travels, and the SPA turns it into a sentence an operator can act on")
# ⚠️ THE RECORDS BELOW ARE THE PANEL'S OWN OUTPUT, UNEDITED. Retyping them here would test two fixtures
# that agree and leave the field free to stop travelling.
probe = os.path.join(HERE, "_xtoo_probe.mjs")
spa = os.path.join(ROOT, "js", "routing.js")
mod = "routing.js"
if PS:
    src = open(spa, encoding="utf-8").read()
    a = "  if ((node || {}).exits_unsupported)\n"
    assert src.count(a) == 1, "SPA anchor missing — this run would FALSE-PASS"
    src = src.replace(a, "  if (false)\n")
    mod = "__xtoo_perturb.js"
    open(os.path.join(ROOT, "js", mod), "w", encoding="utf-8").write(src)
open(probe, "w").write("""
import { ROOT } from "./spa_env.mjs";
import { pathToFileURL } from "node:url"; import path from "node:path"; import fs from "node:fs";
const { exitHealth, exitHealthMark } = await import(pathToFileURL(path.join(ROOT, "js", process.argv[2])).href);
const { Store } = await import(pathToFileURL(path.join(ROOT, "js", "store.js")).href);
const nodes = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = {};
for (const [id, n] of Object.entries(nodes)) {
  Store.nodes = [n]; Store.recon.nodeStatus = { [id]: "live" };
  out[id] = {};
  for (const ex of n.exits || []) {
    const h = exitHealth(ex, n);
    exitHealthMark(h);                       // the marker must render for the new state too
    out[id][ex.producer] = { state: h.state, tone: h.tone || "", icon: h.icon || "", why: h.why };
  }
}
process.stdout.write(JSON.stringify(out));
""")
tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump(N, tf); tf.close()
r = subprocess.run([os.environ.get("NODE_BIN", "node"), probe, mod, tf.name],
                   capture_output=True, text=True, cwd=ROOT)
os.unlink(probe); os.unlink(tf.name)
if PS:
    os.unlink(os.path.join(ROOT, "js", mod))
if r.returncode != 0:
    check("the SPA probe ran", False, r.stderr[-400:])
    V = {}
else:
    V = json.loads(r.stdout)

for prod in ("imported", "adopted"):
    v = (V.get("old") or {}).get(prod) or {}
    check("an %s exit on a too-old node reads `unsupported`" % prod, v.get("state") == "unsupported", v)
    check("…and it WARNS rather than pretending to be busy", v.get("tone") == "warn" and v.get("icon") == "warn", v)
    check("…and the sentence names the node and what to do about it",
          "too old" in (v.get("why") or "") and "Update the node" in (v.get("why") or ""), v.get("why"))

print("\n[3] ⚠️ and it does NOT swallow the real states it sits above")
check("an imported exit on a CURRENT node still reads `creating`",
      ((V.get("new") or {}).get("imported") or {}).get("state") == "creating", (V.get("new") or {}).get("imported"))
check("…and on a node that has never synced, likewise",
      ((V.get("never") or {}).get("imported") or {}).get("state") == "creating", (V.get("never") or {}).get("imported"))
check("an adopted exit on a CURRENT node still reads `unreported` (no candidate by that name)",
      ((V.get("new") or {}).get("adopted") or {}).get("state") == "unreported", (V.get("new") or {}).get("adopted"))

print("\n[4] ⚠️ the field must reach the reader — the node argument is the RAW record, never a draft")
# [[whitelist-rebuild-drops-fields]]. `nFields` rebuilds a node from a key list and would drop this field
# in silence; it exists so a server-derived verdict cannot make the Save button light up. It is used for
# `vals` and for `exits`, never as the `node` argument — and swapping one for the other is exactly how this
# fix would stop working with every check above still green. Cheap to assert, so assert it.
import re as _re
_bad = []
for _f in ("js/routing.js", "js/screen-settings.js"):
    for _i, _ln in enumerate(open(os.path.join(ROOT, _f), encoding="utf-8"), 1):
        if _re.search(r"(exitHealth|exitOptionGroups)\([^)]*nFields\(", _ln):
            _bad.append("%s:%d" % (_f, _i))
check("no health/picker call is handed an nFields draft as its node", not _bad, _bad)
_nf = open(os.path.join(ROOT, "js", "screen-settings.js"), encoding="utf-8").read()
check("…and nFields still does not carry the field (it is panel-derived, not operator-owned)",
      "exits_unsupported" not in _nf.split("const nFields")[1].split("const [nodeEdits")[0])

print()
if PP or PS:
    ok = bool(FAILS)
    print(("PERTURB OK (%s) — %d checks went red" % ("panel" if PP else "spa", len(FAILS))) if ok
          else "PERTURB FAILED — the fix was removed and every check still passed")
    sys.exit(0 if ok else 1)
print(("FAILED: " + ", ".join(FAILS)) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
