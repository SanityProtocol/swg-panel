#!/usr/bin/env python3
"""Self-test — THE SUBSCRIPTION ADDRESS: THE OPERATOR'S IS ENFORCED, NOBODY'S IS RECORDED, AND THE ROOT HELPER RUNS THE
PANEL'S REQUESTS IN THE ORDER THEY WERE MADE.

The panel reads its settings MERGED WITH THE DEFAULTS, so 0.0.0.0:8444 read as "configured" on every box where nobody set
a subscription address. Its start-up reconcile enforced that: a bare panel behind the operator's own reverse proxy
(swg-sub on 127.0.0.1) had swg-sub moved to 0.0.0.0 at its second start (1.8.8 qualification, round 9), and a SUB_PORT
given at install went back to 8444 — or, once that was stopped (feb2d99), stayed while Settings and every link said 8444
(round 9b). Now: an address the operator chose (sub_bind_by "operator", or before that a non-default value) is enforced;
nobody's is recorded from what swg-sub runs with; and the second start's footprint is undone where it is unmistakable.

  [1] nobody chose, no drop-in, unit on 127.0.0.1:8444 → nothing queued; the settings record 127.0.0.1:8444 ("install")
  [2] the footprint — swg-netctl's own drop-in with 0.0.0.0:8444, nobody chose, the unit on loopback → set-listen the
      unit's bind, THEN restart, in the order the helper runs them (300 runs); one line names what was undone and how to
      choose every address on purpose; the settings record the unit's bind. ⚠️ Neither line says "nobody set": the same
      footprint is left by a choice made in Settings under 1.8.7, which kept no record of it (round 10, N5) — the line
      names both, and says to set it again
  [3] …with the unit on 127.0.0.1:8446 → back on 127.0.0.1:8446
  [4] NOT undone: the operator chose 0.0.0.0:8444 (sub_bind_by "operator") — the same drop-in stays
  [5] NOT undone: a non-proxy install (the unit on 0.0.0.0) — the drop-in stays, nothing recorded (it runs the default)
  [6] NOT undone: a drop-in that is not swg-netctl's (the operator's own file) — and what it gives is what is recorded
  [7] NOT undone: a legacy non-default choice (0.0.0.0:8446, no marker) is the operator's — enforced, not recorded over
  [8] the operator's address with no drop-in (a convert deleted it) and the unit elsewhere → re-asserted; with the unit
      already on it → nothing (no needless restart)
  [9] SUB_PORT given at install (the unit on 0.0.0.0:8446), nobody chose → the settings record 8446; _SUB_LIVE_BIND and
      serve.json follow
  [10] Docker: nobody chose and compose publishes 127.0.0.1:8446 → recorded; the operator chose → not; no env → not
  [11] a settings save that MOVES the address is the operator's choice; one that leaves it where it was is not
  [12] no queue yet → "could not be put back", never "it is back on"
  [13] swg-sub not installed / a declarative host → nothing
  [14] fifty requests sort in the order they were made; each name survives both helpers' sanitizing; both run sorted

Run: python3 tests/sub_bind_default_selftest.py        (0 = pass)
     --perturb-heal      the footprint left in place → [2][3] red
     --perturb-loopback  the heal without the loopback condition → [5] red
     --perturb-marker    the operator's choice ignored → [4] red
     --perturb-ours      the heal without the swg-netctl mark → [6] red
     --perturb-record    nobody's address not recorded → [1][9] red
     --perturb-order     the random request name put back → [2][14] red
     --perturb-claim     "it is back on" printed whatever the queue said → [12] red
     --perturb-wording   the heal says "an address nobody set" again → [2] red
"""
import ast, contextlib, io, json, os, re, socket, sys, tempfile
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PSRC = open(os.path.join(ROOT, "swg-panel-server"), encoding="utf-8").read()
NSRC = open(os.path.join(ROOT, "swg-netctl"), encoding="utf-8").read()
DSRC = open(os.path.join(ROOT, "docker", "swg-netctl-docker"), encoding="utf-8").read()
CSRC = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()


def plant(src, old, new):
    assert src.count(old) == 1, "perturbation anchor not found once: %r" % old[:80]
    return src.replace(old, new)


if "--perturb-heal" in sys.argv:
    PSRC = plant(PSRC, '                and _is_loopback(unit["host"])):\n', '                and _is_loopback(unit["host"]) and False):\n')
if "--perturb-loopback" in sys.argv:
    PSRC = plant(PSRC, '                and _is_loopback(unit["host"])):\n', '                ):\n')
if "--perturb-marker" in sys.argv:
    PSRC = plant(PSRC, '    if by in ("operator", "install"):\n        return by == "operator"\n', "")
if "--perturb-ours" in sys.argv:
    PSRC = plant(PSRC, '        if (unit and drop and drop["ours"] and ', '        if (unit and drop and ')
if "--perturb-record" in sys.argv:
    PSRC = plant(PSRC, '        if run and (run["host"], run["port"]) != want:\n            _record_sub_bind(', '        if False:\n            _record_sub_bind(')
if "--perturb-order" in sys.argv:
    PSRC = plant(PSRC, 'rid = "acc-%013x%04x-%s" % (time.time_ns() // 1000, next(_NETCTL_SEQ) & 0xffff, secrets.token_hex(4))',
                 'rid = "acc-" + secrets.token_hex(6)')
if "--perturb-wording" in sys.argv:
    PSRC = plant(PSRC, '                why = ("an earlier panel\'s start wrote it — or it was chosen in Settings under a release before 1.8.8, "\n'
                       '                       "which kept no record of that choice")\n',
                 '                why = "an earlier panel\'s start wrote an address nobody set"\n')
if "--perturb-claim" in sys.argv:
    PSRC = plant(PSRC, '            if (_netctl_enqueue(deps, "set-listen", ["sub", unit["host"], unit["port"]])\n                    and (not running or _netctl_enqueue(deps, "restart", ["sub"]))):',
                 '            _netctl_enqueue(deps, "set-listen", ["sub", unit["host"], unit["port"]])\n            if True:')

mod = ast.parse(PSRC)
seg = {n.name: ast.get_source_segment(PSRC, n) for n in mod.body if isinstance(n, ast.FunctionDef)}
def assign(name):
    return next(ast.get_source_segment(PSRC, n) for n in mod.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
LIFT = "\n".join(assign(n) for n in ("PANEL_SETTINGS_DEFAULTS", "_NETCTL_SEQ", "SUB_UNIT_FILE", "SUB_DROPIN_FILE",
                                      "_NETCTL_DROPIN_MARK")) + "\n\n" + "\n\n".join(
    seg[n] for n in ("_is_loopback", "_netctl_enqueue", "_sub_bind_of", "_sub_bind_in", "_sub_bind_chosen",
                     "_note_sub_bind_choice", "_sub_url_port", "_sub_url_on_port", "_record_sub_bind", "_flag_sub_url_port",
                     "_reconcile_sub_listen_at_boot"))

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "\n     " + str(detail)[:700]))
    if not ok:
        fails.append(name)


UNIT = """[Unit]
Description=swg-sub
[Service]
ExecStart=/opt/swg-sub/swg-sub
Environment=SWG_SUB_FLEET=/etc/swg-panel/fleet.json
Environment=SWG_SUB_HOST=%s
Environment=SWG_SUB_PORT=%s
"""
NETCTL_DROPIN = "# managed by swg-netctl — from the panel's Access & TLS settings; do not edit by hand\n[Service]\nEnvironment=SWG_SUB_HOST=%s\nEnvironment=SWG_SUB_PORT=%s\n"
OWN_DROPIN = "[Service]\nEnvironment=SWG_SUB_HOST=%s\nEnvironment=SWG_SUB_PORT=%s\n"


def run_case(sub=None, by=None, unit=None, dropin=None, own=False, queue=True, present=True, docker=False,
             declarative=False, env=None):
    """→ (requests the helper would run, in its order, as (verb, args)), the log, the settings as saved (or None),
    _SUB_LIVE_BIND, serve.json writes"""
    import itertools, ipaddress, secrets, time
    d = tempfile.mkdtemp()
    ns = {"os": os, "re": re, "json": json, "contextlib": contextlib, "itertools": itertools, "ipaddress": ipaddress,
          "secrets": secrets, "time": time, "VK_POOL_PER_USER_DEFAULT": 3, "IN_DOCKER": docker,
          "PANEL_DECLARATIVE": declarative, "NETCTL_LIFECYCLE_VERBS": frozenset(("restart", "reload")),
          "panel_service_health": lambda ttl=20: {"sub": {"present": present, "active": "active"}},   # a running swg-sub (a stopped one: sub_port_kept_selftest)
          "urlparse": urlparse, "socket": socket, "ev_append": lambda *a, **k: None}
    saved, serve = [], []
    ns["save_critical"] = lambda p, text: saved.append(json.loads(text))
    ns["write_sub_serve"] = lambda deps, base_alt="": serve.append(dict(((deps["panel_settings"].get("access") or {}).get("sub")) or {}))
    ns.update(log=lambda prio, msg, *a: print((msg % a) if a else msg, flush=True),   # the panel's log helper (LOGS P1b)
              LOG_ERR=3, LOG_WARNING=4, LOG_NOTICE=5, LOG_INFO=6, LOG_DEBUG=7)
    exec(compile(LIFT, "swg-panel-server(extract)", "exec"), ns)
    ns["SUB_UNIT_FILE"] = os.path.join(d, "swg-sub.service")
    ns["SUB_DROPIN_FILE"] = os.path.join(d, "10-access.conf")
    if unit:
        open(ns["SUB_UNIT_FILE"], "w").write(UNIT % unit)
    if dropin:
        open(ns["SUB_DROPIN_FILE"], "w").write((OWN_DROPIN if own else NETCTL_DROPIN) % dropin)
    if queue:
        os.makedirs(os.path.join(d, "netctl", "queue"))
    ps = json.loads(json.dumps(ns["PANEL_SETTINGS_DEFAULTS"]))     # merged, as load_panel_settings gives it
    if sub:
        ps["access"]["sub"].update(sub)
    if by:
        ps["sub_bind_by"] = by
    ns["_SUB_LIVE_BIND"] = {"host": str(ps["access"]["sub"]["host"]), "port": int(ps["access"]["sub"]["port"])}
    deps = {"nodes_path": os.path.join(d, "nodes.json"), "panel_settings": ps, "panel_settings_path": os.path.join(d, "ps.json")}
    old_env = {k: os.environ.get(k) for k in ("SWG_PANEL_SUB_BIND", "SWG_PANEL_SUB_PORT")}
    for k, v in (env or {}).items():
        os.environ[k] = v
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            ns["_reconcile_sub_listen_at_boot"](deps)
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    reqs = []
    if queue:
        q = os.path.join(d, "netctl", "queue")
        for name in sorted(os.listdir(q)):                      # the order swg-netctl runs them
            j = json.load(open(os.path.join(q, name)))
            reqs.append((j["verb"], j["args"]))
    return reqs, out.getvalue(), (saved[-1] if saved else None), ns["_SUB_LIVE_BIND"], serve


def rec_bind(saved):
    return saved and (str(saved["access"]["sub"]["host"]), str(saved["access"]["sub"]["port"]), saved.get("sub_bind_by"))


r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"))
check("[1] nobody chose, no drop-in, unit on loopback → nothing queued", r == [], (r, log))
check("[1] …the settings record the unit's bind, as the installer's", rec_bind(sv) == ("127.0.0.1", "8444", "install"), (sv and sv.get("access"), log))

bad = last = 0
for i in range(300):
    r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8444"))
    if r != [("set-listen", ["sub", "127.0.0.1", "8444"]), ("restart", ["sub"])]:
        bad += 1; last = r
check("[2] the footprint → set-listen the unit's bind, THEN restart, in the helper's order (300 runs)", bad == 0,
      "%d of 300 wrong/out of order, e.g. %r" % (bad, last))
check("[2] …one line names what was undone and how to choose every address on purpose",
      "was listening on 0.0.0.0:8444" in log and "back on 127.0.0.1:8444" in log
      and "Settings → Panel access → Subscription address" in log, log)
check("[2] …and it does not say \"nobody set\": an earlier start OR a choice made under a release before 1.8.8, which kept no "
      "record of it — and to set it again (N5)",
      "nobody set" not in log and "or it was chosen in Settings under a release before 1.8.8, which kept no record of that choice" in log
      and "set it again in Settings → Panel access → Subscription address" in log
      and "(Settings showed 0.0.0.0:8444, which no Settings save of this release chose)" in log, log)
check("[2] …and the settings record the unit's bind", rec_bind(sv) == ("127.0.0.1", "8444", "install")
      and live == {"host": "127.0.0.1", "port": 8444} and serve and serve[-1].get("host") == "127.0.0.1", (sv, live, serve))

r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8446"), dropin=("0.0.0.0", "8444"))
check("[3] …with the unit on 127.0.0.1:8446 → back on 127.0.0.1:8446",
      r == [("set-listen", ["sub", "127.0.0.1", "8446"]), ("restart", ["sub"])] and rec_bind(sv) == ("127.0.0.1", "8446", "install"), (r, sv))

r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8444"), by="operator")
check("[4] NOT undone: the operator chose 0.0.0.0:8444 — nothing queued, nothing recorded", r == [] and sv is None and log == "", (r, sv, log))

r, log, sv, live, serve = run_case(unit=("0.0.0.0", "8444"), dropin=("0.0.0.0", "8444"))
check("[5] NOT undone: a non-proxy install — nothing queued, nothing recorded", r == [] and sv is None, (r, sv, log))

r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8444"), own=True)
check("[6] NOT undone: a drop-in that is not swg-netctl's — nothing queued", r == [], (r, log))
check("[6] …and what it gives (0.0.0.0:8444, the default) is what the settings hold — nothing recorded", sv is None, sv)
r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "9000"), own=True)
check("[6] …the operator's own file on 0.0.0.0:9000 → recorded as where swg-sub listens", r == [] and rec_bind(sv) == ("0.0.0.0", "9000", "install"), (r, sv))

r, log, sv, live, serve = run_case(sub={"port": 8446}, unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8446"))
check("[7] NOT undone: a legacy non-default choice (0.0.0.0:8446, no marker) — enforced as it runs, not recorded over",
      r == [] and sv is None, (r, sv, log))

r, log, sv, live, serve = run_case(sub={"port": 8446}, unit=("0.0.0.0", "8444"))
check("[8] the operator's address, no drop-in (a convert deleted it), the unit elsewhere → re-asserted",
      r == [("set-listen", ["sub", "0.0.0.0", "8446"]), ("restart", ["sub"])] and "re-applied the subscription bind 0.0.0.0:8446" in log, (r, log))
r, log, sv, live, serve = run_case(sub={"host": "0.0.0.0", "port": 8444}, by="operator", unit=("0.0.0.0", "8444"))
check("[8] …the operator's address already what the unit runs → nothing (no needless restart)", r == [] and sv is None, (r, sv))
r, log, sv, live, serve = run_case(sub={"host": "0.0.0.0", "port": 8444}, by="operator", unit=("127.0.0.1", "8444"))
check("[8] …the operator chose 0.0.0.0:8444 on a proxy install and the drop-in went → re-asserted (their choice)",
      r == [("set-listen", ["sub", "0.0.0.0", "8444"]), ("restart", ["sub"])], (r, log))

r, log, sv, live, serve = run_case(unit=("0.0.0.0", "8446"))
check("[9] SUB_PORT given at install (the unit on 0.0.0.0:8446), nobody chose → recorded 8446, nothing queued",
      r == [] and rec_bind(sv) == ("0.0.0.0", "8446", "install"), (r, sv, log))
check("[9] …_SUB_LIVE_BIND and serve.json follow", live == {"host": "0.0.0.0", "port": 8446} and serve and serve[-1].get("port") == 8446, (live, serve))

r, log, sv, live, serve = run_case(docker=True, env={"SWG_PANEL_SUB_BIND": "127.0.0.1", "SWG_PANEL_SUB_PORT": "8446"})
check("[10] Docker, nobody chose, compose publishes 127.0.0.1:8446 → recorded", r == [] and rec_bind(sv) == ("127.0.0.1", "8446", "install"), (r, sv))
r, log, sv, live, serve = run_case(docker=True, by="operator", env={"SWG_PANEL_SUB_BIND": "127.0.0.1", "SWG_PANEL_SUB_PORT": "8446"})
check("[10] …the operator chose → not recorded over", sv is None, sv)
r, log, sv, live, serve = run_case(docker=True)
check("[10] …no env (an older compose file) → nothing", sv is None and r == [], (sv, r))
check("[10] docker-compose.yml hands the panel swg-sub's publish (SUB_BIND / SUB_PORT)",
      'SWG_PANEL_SUB_BIND: "${SUB_BIND:-0.0.0.0}"' in CSRC and 'SWG_PANEL_SUB_PORT: "${SUB_PORT:-8444}"' in CSRC)

ns11 = {"PANEL_SETTINGS_DEFAULTS": None}
exec(compile(assign("PANEL_SETTINGS_DEFAULTS").replace("VK_POOL_PER_USER_DEFAULT", "3") + "\n" + seg["_sub_bind_of"] + "\n"
             + seg["_note_sub_bind_choice"], "x", "exec"), ns11)
s1 = {}; ns11["_note_sub_bind_choice"]({"sub": {"host": "127.0.0.1", "port": 8444}}, {"sub": {"url": "x", "host": "127.0.0.1", "port": 8444}}, s1)
s2 = {}; ns11["_note_sub_bind_choice"]({"sub": {"host": "127.0.0.1", "port": 8444}}, {"sub": {"host": "0.0.0.0", "port": 8444}}, s2)
check("[11] a save that MOVES the address is the operator's; one that leaves it is not", s1 == {} and s2 == {"sub_bind_by": "operator"}, (s1, s2))
check("[11] …and the settings save calls it before it stores the new access block",
      '            _note_sub_bind_choice(cur.get("access"), _acc_clean, cur)   # a MOVED subscription address is the operator\'s\n            cur["access"] = _acc_clean\n' in PSRC)

r, log, sv, live, serve = run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8444"), queue=False)
check("[12] no queue yet → 'could not be put back', never 'it is back on'", "could not be put back" in log and "it is back on" not in log, log)

ok13 = all(run_case(unit=("127.0.0.1", "8444"), dropin=("0.0.0.0", "8444"), **kw)[0:3:2] == ([], None)
           for kw in ({"present": False}, {"declarative": True}))
check("[13] swg-sub not installed / declarative → nothing", ok13)

import itertools, secrets, time
ns = {"os": os, "json": json, "contextlib": contextlib, "itertools": itertools, "secrets": secrets, "time": time,
      "PANEL_DECLARATIVE": False, "NETCTL_LIFECYCLE_VERBS": frozenset(("restart", "reload"))}
exec(compile(assign("_NETCTL_SEQ") + "\n\n" + seg["_netctl_enqueue"], "x", "exec"), ns)
d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "netctl", "queue"))
made = [ns["_netctl_enqueue"]({"nodes_path": os.path.join(d, "nodes.json")}, "restart", ["sub"]) for _ in range(50)]
ran = [n[:-5] for n in sorted(os.listdir(os.path.join(d, "netctl", "queue")))]
check("[14] fifty requests sort in the order they were made", ran == made, (made[:3], ran[:3]))
_sr = {}
exec(compile(ast.get_source_segment(NSRC, next(n for n in ast.parse(NSRC).body
                                              if isinstance(n, ast.FunctionDef) and n.name == "_safe_rid")),
             "swg-netctl(extract)", "exec"), {"os": os, "re": re}, _sr)
check("[14] …each name survives swg-netctl's _safe_rid unchanged, and all are unique",
      all(_sr["_safe_rid"](m + ".json") == m for m in made) and len(set(made)) == 50, made[:2])
_dl = next((ln.strip() for ln in DSRC.splitlines() if 'rid = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(rid))' in ln), "")
_dexpr = _dl.split("=", 1)[1].split("#", 1)[0].strip() if _dl else "None"
check("[14] …and swg-netctl-docker's own sanitizing leaves each unchanged",
      bool(_dl) and all(eval(_dexpr, {"re": re, "os": os, "rid": m}) == m for m in made), _dl or "the Docker helper's line moved")
check("[14] both helpers run their queue sorted by name",
      "        for name in sorted(os.listdir(qfd)):" in NSRC and "    for name in sorted(os.listdir(QUEUE)):" in DSRC)

print("\n%s — %d check(s) failed" % ("FAIL", len(fails)) if fails else "\nPASS — all checks")
sys.exit(1 if fails else 0)
