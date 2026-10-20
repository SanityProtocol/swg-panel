#!/usr/bin/env python3
"""Self-test: a node whose rules exit through an OFFLINE node says so on its card (q189 FLA-F1).

Measured on the operator's msk-main: its default list sent google, github and discord through hel-fresh, offline for ~9.6
days — every client following the list lost Google (Google DNS included), GitHub and Discord, dropped (fail-closed, never
leaked) and said nowhere: the card carried no issue, while a torrent route whose way out is down already says so.

  [1] the default list's exit rule through a node offline (twice the cards' stale line) → one issue naming that node,
      through the real /api/state build; nothing on the offline node's own card
  [2] the same node online → no issue (a node one sync late is not offline)
  [3] an interface's smart exit rule, a forward's egress node and a WDTT instance's rule count too; a rule switched off does
      not; two rules through one node are one issue; a node's rules through itself never are
  [4] the sentence has its Russian

Hermetic (the panel module in-process). Run: python3 tests/exit_node_offline_selftest.py   (0 = pass)
     --perturb   the issue builder ignores the offline exits → RED
"""
import json, os, sys, tempfile, time, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
KEY = "Routing on this node sends traffic out through {v1}, which is offline — that traffic is refused until {v1} is back"

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(SERVER, encoding="utf-8").read()
if PERTURB:
    a = "    for _xn in exits_offline or ():\n"
    if src.count(a) != 1:
        print("PERTURB FAILED — anchor missing"); sys.exit(1)
    src = src.replace(a, "    for _xn in ():\n")
P = types.ModuleType("swgpanel_exitoff"); P.__file__ = SERVER
exec(compile(src, SERVER, "exec"), P.__dict__)

def state(nodes, seen):
    tmp = tempfile.mkdtemp(); np_, rp = os.path.join(tmp, "nodes.json"), os.path.join(tmp, "users.json")
    json.dump(nodes, open(np_, "w")); json.dump({"version": P.ROSTER_VERSION, "users": {}, "peers": {}}, open(rp, "w"))
    d = {"nodes_path": np_, "roster_path": rp, "stats_dir": tmp, "fleet": {}, "panel_settings": {},
         "node_snaps": {n: {"hostname": n} for n in nodes}, "node_seen": seen}
    P.Handler.deps = d
    code, obj = P.api("GET", "/api/state", {}, {}, d)
    return {n["id"]: [i.get("error_key") or i.get("error") for i in (n.get("issues_i18n") or [])] for n in (obj.get("data") or {}).get("nodes") or []}, \
           {n["id"]: n.get("issues_i18n") or [] for n in (obj.get("data") or {}).get("nodes") or []}

now = time.time()
BASE = {"msk": {"name": "msk-main", "ifaces": {}, "default_routing": [{"category": "google", "action": "exit", "node": "hel"},
                                                                       {"category": "github", "action": "exit", "node": "hel"}]},
        "hel": {"name": "hel-fresh", "ifaces": {}}, "svo": {"name": "svo-im", "ifaces": {}}}
print("[1] the default list through a node offline for days")
k, full = state(BASE, {"msk": now, "hel": now - 9.6 * 86400, "svo": now})
check("msk-main's card names hel-fresh once (two rules, one node)", k.get("msk", []).count(KEY) == 1
      and [i.get("error_vars", {}).get("v1") for i in full["msk"] if i.get("error_key") == KEY] == ["hel-fresh"], full.get("msk"))
check("…and nothing of the kind on hel-fresh's or svo-im's", KEY not in k.get("hel", []) and KEY not in k.get("svo", []), k)
print("\n[2] the same node online")
k, _ = state(BASE, {"msk": now, "hel": now - 40, "svo": now})
check("hel-fresh one sync late is not offline: no issue", KEY not in k.get("msk", []), k.get("msk"))
print("\n[3] every way out counts, and only those")
N3 = {"msk": {"name": "msk-main", "ifaces": {
          "awg1": {"egress_mode": "smart", "routing": [{"category": "youtube", "action": "exit", "node": "hel"}]},
          "wg2": {"egress_mode": "forward", "egress_node": "svo"},
          "awg3": {"egress_mode": "smart", "routing": [{"category": "discord", "action": "exit", "node": "nix", "who": {"on": False}}]},
          "swg_x": {"system": True, "egress_mode": "forward", "egress_node": "nix"}},
          "wdtt": {"wdtt0": {"egress_mode": "smart", "routing": [{"category": "all", "action": "exit", "node": "fin"}]}},
          "default_routing": [{"category": "google", "action": "exit", "node": "msk"}]},
      "hel": {"name": "hel-fresh", "ifaces": {}}, "svo": {"name": "svo-im", "ifaces": {}}, "nix": {"name": "nixos", "ifaces": {}},
      "fin": {"name": "fin-1", "ifaces": {}}}
gone = now - 3600
k, full = state(N3, {"msk": now, "hel": gone, "svo": gone, "nix": gone, "fin": gone})
named = sorted(i.get("error_vars", {}).get("v1") for i in full.get("msk", []) if i.get("error_key") == KEY)
check("an interface's smart rule, a forward and a WDTT rule each name their offline node", named == ["fin-1", "hel-fresh", "svo-im"], named)
check("…a rule switched off and a mesh link name nothing (nixos), nor a rule through the node itself", "nixos" not in named and "msk-main" not in named, named)
print("\n[4] Russian")
ru = open(os.path.join(ROOT, "js", "lang", "ru.js"), encoding="utf-8").read()
check("the sentence has its Russian line", json.dumps(KEY, ensure_ascii=False) + ":" in ru)

print()
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS else "PERTURB FAILED — every check passed"); sys.exit(0 if FAILS else 1)
if FAILS:
    print("FAILED: %d — %s" % (len(FAILS), "; ".join(FAILS))); sys.exit(1)
print("ALL PASS")
