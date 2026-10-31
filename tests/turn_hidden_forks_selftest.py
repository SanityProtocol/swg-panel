#!/usr/bin/env python3
"""Self-test: the forks and apps hidden on the operator's word (2026-10-14) stay out of every offer, and nothing a node
already runs loses what it has.

MYSOREZ and Moroka8 have not moved upstream since July / June 2026; XXcipherX deleted its repository. They join cacggghp in
TURN_HIDDEN_FORKS — out of every operator picker, still in the catalog so a proxy a node runs keeps its name, colour and
editor. The MYSOREZ Android app and XXcipherX's app are hidden the same way (TURN_HIDDEN_CLIENTS): a visible fork no
longer offers them, a hidden fork keeps the map it had, so its users keep their app.

  [1] the served catalog (turn_catalog_view, what the SPA and serve.json read): the four hidden forks say hidden, the rest
      do not; no visible fork offers a hidden app in `compat` or `client_schemas`, nor a hidden fork's CLI build in
      `cli_authors` (hack-diaz and anton48 offered Moroka8's); each hidden fork keeps its map (MYSOREZ's own app,
      Moroka8's CLI) — but no fork offers a GONE app (XXcipherX's: a running xxcipherx server's users get the next WDTT
      app, never a dead link); the apps stay in the clients map, which the hidden forks' users still need
  [2] the Settings save (/api/panel/settings, the real handler): a visible fork's default naming a hidden app or a hidden
      fork's CLI build is dropped, its other choices kept; a hidden fork's own default is kept, a gone app is not
  [3] the Client rosters sheet (its P1 report — neither app is a P4 one) lists no GONE app (XXcipherX's sources are
      deleted) but keeps the MYSOREZ app — alive upstream, still served to the hidden forks — and a visible one

Hermetic (GitHub reads are stubbed). Run: python3 tests/turn_hidden_forks_selftest.py   (0 = pass)
     --perturb          TURN_HIDDEN_CLIENTS empty again (the apps offered by every fork) → RED in [1] and [2]
     --perturb-cli      a visible fork offers a hidden fork's CLI build again (_turn_cli_authors unfiltered) → RED in [1], [2]
     --perturb-roster   the roster report lists every app again → RED in [3]
     --perturb-gone     a hidden fork keeps a gone app (XXcipherX's) → RED in [1] and [2]
     --perturb-line25   a 2.1-only app is stored under csqtt@2.5 → RED in [4]
"""
import atexit, importlib.machinery, importlib.util, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SERVER = os.environ.get("SWG_PANEL_SERVER") or os.path.join(ROOT, "swg-panel-server")
PERTURB = "--perturb" in sys.argv
PERTURB_CLI = "--perturb-cli" in sys.argv
PERTURB_ROSTER = "--perturb-roster" in sys.argv
PERTURB_GONE = "--perturb-gone" in sys.argv
PERTURB_LINE25 = "--perturb-line25" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:500]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

TMP = tempfile.mkdtemp(prefix="turnhidden-")
atexit.register(shutil.rmtree, TMP, True)   # the copied panel is ~4.6 MB, and the nightly runs this five times
src = open(SERVER, encoding="utf-8").read()
def plant(a, b, what):
    global src
    if src.count(a) != 1:
        print("PERTURB FAILED — %s: the anchor is not in the panel exactly once (%d)" % (what, src.count(a))); sys.exit(1)
    src = src.replace(a, b)
    print("(perturbed: %s — this run must FAIL)" % what)
if PERTURB:
    plant('TURN_HIDDEN_CLIENTS = {"mysorez", "xxcipher"}\n', "TURN_HIDDEN_CLIENTS = set()\n", "no app hidden")
if PERTURB_CLI:
    plant("    return a if sid in TURN_HIDDEN_FORKS else [x for x in a if x not in TURN_HIDDEN_FORKS]\n", "    return a\n",
          "every CLI build offered")
if PERTURB_ROSTER:
    plant("        if cid in TURN_GONE_CLIENTS:\n            continue                                    # its repository is gone: nothing to watch, and no row",
          "        if False:\n            continue", "the roster lists every app")
if PERTURB_LINE25:
    plant("not line or line in (TURN_CLIENTS[cidv].get(\"csqtt_lines\") or [CSQTT_DEFAULT_LINE])", "True", "the 2.5 key's line check")
if PERTURB_GONE:
    plant('TURN_GONE_CLIENTS = {"xxcipher"}\n', "TURN_GONE_CLIENTS = set()\n", "a gone app kept by its hidden fork")
SRV = os.path.join(TMP, "swg-panel-server")
open(SRV, "w", encoding="utf-8").write(src)
loader = importlib.machinery.SourceFileLoader("swgpanel_turnhidden", SRV)
P = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgpanel_turnhidden", loader))
try:
    loader.exec_module(P)
except SystemExit:
    pass

HIDDEN = {"cacggghp", "MYSOREZ", "Moroka8", "xxcipherx"}
APPS = {"mysorez", "xxcipher"}

print("[1] the served catalog")
cat = P.turn_catalog_view()
srv = {s["id"]: s for s in cat["servers"]}
check("[1] cacggghp, MYSOREZ, Moroka8 and xxcipherx are hidden; no other fork is",
      {sid for sid, s in srv.items() if s.get("hidden")} == HIDDEN, sorted(sid for sid, s in srv.items() if s.get("hidden")))
vis = [sid for sid in srv if sid not in HIDDEN]
leak = {sid: sorted(APPS & set(srv[sid]["compat"])) for sid in vis if APPS & set(srv[sid]["compat"])}
check("[1] no visible fork offers the MYSOREZ app or XXcipherX's (compat)", not leak, leak)
check("[1] …nor carries a schema for one (client_schemas follows compat)",
      all(set(srv[sid]["client_schemas"]) == set(srv[sid]["compat"]) for sid in srv),
      {sid: sorted(set(srv[sid]["client_schemas"]) ^ set(srv[sid]["compat"])) for sid in srv})
check("[1] the visible forks that offered them still offer their other apps (hack-diaz: FreeTurn, the CLI, VK TURN Proxy)",
      set(srv["samosvalishe"]["compat"]) == {"freeturn", "sidecar", "vkturnproxy"}
      and {"wdttapp", "qwdtt", "wdttplus", "vkturnproxy"} <= set(srv["amurcanov"]["compat"]),
      [srv["samosvalishe"]["compat"], srv["amurcanov"]["compat"]])
cli = {sid: srv[sid]["cli_authors"] for sid in vis if set(srv[sid]["cli_authors"]) & HIDDEN}
check("[1] no visible fork offers a hidden fork's CLI build (hack-diaz and anton48 offered Moroka8's)", not cli, cli)
check("[1] …and they keep hack-diaz's", srv["samosvalishe"]["cli_authors"] == ["samosvalishe"]
      and srv["anton48"]["cli_authors"] == ["samosvalishe"], [srv["samosvalishe"]["cli_authors"], srv["anton48"]["cli_authors"]])
check("[1] a hidden fork keeps its map: MYSOREZ its own app, Moroka8 its CLI and the core launcher",
      srv["MYSOREZ"]["compat"].get("mysorez") == "native"
      and srv["Moroka8"]["cli_authors"] == ["Moroka8", "samosvalishe"] and srv["Moroka8"]["compat"].get("mysorez") == "friendly_core",
      [srv["MYSOREZ"]["compat"], srv["Moroka8"]["cli_authors"]])
check("[1] …but no fork offers a GONE app (XXcipherX's, its repository deleted): a running xxcipherx server's users get the next WDTT app",
      not any("xxcipher" in s_["compat"] for s_ in srv.values()) and {"wdttapp", "wdttplus", "qwdtt"} <= set(srv["xxcipherx"]["compat"]),
      srv["xxcipherx"]["compat"])
check("[1] both apps stay in the clients map (a hidden fork's users still get theirs)", APPS <= set(cat["clients"]), sorted(cat["clients"]))

print("\n[2] the Settings save — the real handler")
psp = os.path.join(TMP, "panel-settings.json")
json.dump({}, open(psp, "w"))
deps = {"panel_settings": {}, "panel_settings_path": psp, "nodes_path": os.path.join(TMP, "nodes.json"),
        "roster_path": os.path.join(TMP, "users.json"), "stats_dir": TMP, "fleet": {}, "node_snaps": {}}
json.dump({}, open(deps["nodes_path"], "w"))
body = {"turn_client_default": {
    "samosvalishe": {"android": "mysorez", "linux": "sidecar@Moroka8", "windows": "sidecar@samosvalishe", "ios": "vkturnproxy"},
    "amurcanov": {"android": "xxcipher", "ios": "vkturnproxy"},
    "MYSOREZ": {"android": "mysorez"},
    "xxcipherx": {"android": "xxcipher"}}}
code, rsp = P.api("POST", "/api/panel/settings", {}, body, deps)
saved = (deps.get("panel_settings") or {}).get("turn_client_default") or {}
check("[2] the save is accepted", code == 200, (code, rsp))
check("[2] hack-diaz: the MYSOREZ app and Moroka8's CLI are dropped, its own CLI and VK TURN Proxy kept",
      saved.get("samosvalishe") == {"windows": "sidecar@samosvalishe", "ios": "vkturnproxy"}, saved.get("samosvalishe"))
check("[2] amurcanov: XXcipherX's app is dropped, VK TURN Proxy kept", saved.get("amurcanov") == {"ios": "vkturnproxy"}, saved.get("amurcanov"))
check("[2] a hidden fork's own app is kept as its default (MYSOREZ's); a gone one is not (XXcipherX's)",
      saved.get("MYSOREZ") == {"android": "mysorez"} and saved.get("xxcipherx") == {}, [saved.get("MYSOREZ"), saved.get("xxcipherx")])

body = {"turn_client_default": {"csqtt": {"windows": "focsq"},
    "csqtt@2.5": {"windows": "focsq", "linux": "csqsocks", "android": "csqttapp", "macos": "none", "ios": "vkturnproxy"}, "csqtt@9.9": {"linux": "csqsocks"}}}
code, rsp = P.api("POST", "/api/panel/settings", {}, body, deps)
saved = (deps.get("panel_settings") or {}).get("turn_client_default") or {}
check("[4] csqtt@2.5 (a default per csqtt line, 2026-10-29) is kept beside csqtt's: apps of 2.5 and \"none\" stay, 2.1-only ones (FOCSQ, VK TURN Proxy) are dropped",
      saved.get("csqtt@2.5") == {"linux": "csqsocks", "android": "csqttapp", "macos": "none"} and saved.get("csqtt") == {"windows": "focsq"}, saved)
check("[4] …and no other line's key is invented (csqtt@9.9 dropped)", "csqtt@9.9" not in saved, sorted(saved))

print("\n[3] the Client rosters sheet")
P.TURN_ROSTER_PATH = os.path.join(TMP, "turn-roster.json")
P._gh_latest_commit = lambda *a, **k: None          # hermetic: every fetch "fails"
P._gh_raw = lambda *a, **k: None
p1 = P._turn_roster_check()
p1c = p1.get("clients", p1) if isinstance(p1, dict) else {}
check("[3] the P1 report lists no gone app (XXcipherX's) — and keeps the MYSOREZ app, alive upstream and still served to the hidden forks",
      "xxcipher" not in p1c and "mysorez" in p1c, sorted(APPS & set(p1c)))
check("[3] …and neither is a P4 (field-grid) client, so that report has nothing to hide",
      not any(P._p4_field_client(c) or P._client_value_sources(c) for c in APPS), "")
check("[3] control: a visible app (FreeTurn) is still in the P1 report", "freeturn" in p1c, sorted(p1c))

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURB or PERTURB_CLI or PERTURB_ROSTER or PERTURB_GONE or PERTURB_LINE25:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURB or PERTURB_CLI or PERTURB_ROSTER or PERTURB_GONE or PERTURB_LINE25:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
