#!/usr/bin/env python3
"""Self-test — A RE-INSTALL KEEPS THE SUBSCRIPTION PORT IT WAS INSTALLED WITH, THE URL FOLLOWS A PORT THAT MOVES, AND A
swg-sub THE OPERATOR STOPPED STAYS STOPPED (F92, F93).

F92: install.conf wrote SUB_PORT and nothing read it back — a plain bare re-install took the 8444 default, rewrote
install.conf and swg-sub's unit with it, and swg-sub (still serving the old port until its next restart) then moved to
8444 while the subscription URL typed in Settings kept naming the old port: every link the panel handed out pointed at
a port nothing listened on (1.8.8 qualification, round 10). F93: the panel's start-up heal restarted swg-sub to move its
bind — and `restart` STARTS a stopped unit — then said it "was listening"; every update did the same.

  [1] install-host.sh, driven: the kept install.conf's SUB_PORT is the re-install's (or, with none there, swg-sub's
      unit's); a given SUB_PORT wins; SUB_BIND is kept only when it was once given (install.conf keeps it then)
  [2] install-host.sh, driven: a re-install that changes swg-sub's unit restarts a RUNNING swg-sub onto it; an unchanged
      unit, or a stopped swg-sub (`enable --now` starts it on the new unit), is not restarted. After that restart a running
      panel is restarted too — its start is where the settings record swg-sub's new address (round 12, q5: the panel's
      start came before swg-sub moved, and Settings kept the old port) — never during a convert's deferred start
  [3] the panel (_record_sub_bind): a URL that names the OLD port follows the recorded one (host, scheme, path, an IPv6
      literal kept) — logged and in the activity list; a URL with no port, or with another port, stays
  [4] the panel (_flag_sub_url_port): a URL naming a port where nothing on this box answers is flagged, with both ways
      out; a port something answers on (a reverse proxy), swg-sub's own port, 443 — not. The log says it at every start,
      the activity list once per case (round 12, q5: 17 rows after a morning of restarts): a new case adds a row, the same
      one does not, and a case that resolved and comes back adds one again
  [5] the panel's start (F93): the address is put right for a STOPPED swg-sub too, but only a RUNNING one is restarted,
      and the line says which it was — in the footprint heal and in re-asserting the operator's address
  [6] update.sh restarts swg-sub only when it runs (F93), and its heal (ensure_sub_server) no longer ENABLES one the
      operator disabled and stopped — only one that runs off the boot list (round 12, q5: left stopped, but enabled);
      a Docker re-install keeps SUB_PORT / SUB_BIND from its .env

Run: python3 tests/sub_port_kept_selftest.py        (0 = pass)
     --perturb   nine plants, each on its own — each must turn its own check red
"""
import ast, contextlib, io, json, os, re, socket, subprocess, sys, tempfile
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PATHS = {k: os.environ.get("SWG_SP_" + k) or os.path.join(ROOT, f) for k, f in
         (("HOST", "install-host.sh"), ("PANEL", "swg-panel-server"), ("UPDATE", "update.sh"), ("DOCKER", "install-docker.sh"))}
SRC = {k: open(p, encoding="utf-8").read() for k, p in PATHS.items()}

PLANTS = [
    ("restore", "HOST", 'if [ -z "$_SUB_PORT_GIVEN" ] && [ -n "$SUB_PORT_SAVED" ] && v_port "$SUB_PORT_SAVED"; then SUB_PORT="$SUB_PORT_SAVED"; fi\n',
     "", "[1] the kept install.conf's SUB_PORT is the re-install's"),
    ("restart", "HOST", '  if [ "$_sub_was_up" = yes ] && [ "$(cat "$_subu" 2>/dev/null || true)" != "$_subu_was" ]; then\n',
     '  if false; then\n', "[2] a changed unit restarts a running swg-sub"),
    ("record", "HOST", '        run systemctl restart swg-panel-server && sub "the panel restarted, so its settings record swg-sub\'s new address"\n',
     '        :\n', "[2] …and then a running panel is restarted, to record swg-sub's new address"),
    ("once", "PANEL", '    if seen != case:\n', '    if True:\n', "[4] …the log at every start, the activity list ONE row per case"),
    ("follow", "PANEL", '        if moved:\n            sub["url"] = moved\n', '        pass\n',
     "[3] a URL naming the old port follows the recorded one"),
    ("flag", "PANEL", '    if not up or str(up) == str(listen_port) or up in (80, 443):\n        return _clear()\n',
     '    return _clear()\n', "[4] a URL naming a port nothing answers on is flagged"),
    ("stopped", "PANEL", '                    and (not running or _netctl_enqueue(deps, "restart", ["sub"]))):\n',
     '                    and _netctl_enqueue(deps, "restart", ["sub"])):\n', "[5] the footprint heal: a stopped swg-sub is set right, not restarted"),
    ("update", "UPDATE", '      elif ! $DRYRUN && ! systemctl is-active --quiet swg-sub 2>/dev/null; then\n',
     '      elif false; then\n', "[6] update.sh restarts swg-sub only when it runs"),
    ("enable", "UPDATE", '    if ! $DRYRUN && ! systemctl is-enabled --quiet swg-sub 2>/dev/null && systemctl is-active --quiet swg-sub 2>/dev/null; then\n',
     '    if ! $DRYRUN && ! systemctl is-enabled --quiet swg-sub 2>/dev/null; then\n', "[6] ensure_sub_server leaves a disabled, stopped swg-sub disabled"),
]
if "--perturb" in sys.argv:
    bad = 0
    for name, key, old, new, must in PLANTS:
        src = SRC[key]
        if src.count(old) != 1:
            print("  %-8s STALE ANCHOR (%d) — this plant would plant nothing" % (name, src.count(old))); bad += 1; continue
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix="-" + name); f.write(src.replace(old, new)); f.close()
        r = subprocess.run([sys.executable, __file__], env=dict(os.environ, **{"SWG_SP_" + key: f.name}),
                           capture_output=True, text=True, timeout=300)
        os.unlink(f.name)
        red = ("FAIL " + must) in r.stdout and r.returncode != 0
        print("  %-8s %s" % (name, "caught" if red else ("CRASHED" if "Traceback" in r.stderr else "NOT CAUGHT")))
        bad += not red
    print("%d plants, %d caught" % (len(PLANTS), len(PLANTS) - bad))
    sys.exit(1 if bad else 0)

FAILS = []
def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:700]) if detail and not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)

def line_of(src, needle):
    i = src.index(needle)
    return src[src.rindex("\n", 0, i) + 1:src.index("\n", i) + 1]

def span(src, start, end):
    i = src.index(start); j = src.index(end, i) + len(end)
    return src[i:j] if src[j - 1] == "\n" else src[i:src.index("\n", j) + 1]

def bash(script, env=None):
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True, text=True,
                       env=dict(os.environ, **(env or {})), timeout=60)
    return r.returncode, r.stdout + r.stderr

H = SRC["HOST"]
print("[1] install-host.sh: the subscription address a re-install keeps")
GIVEN = line_of(H, '_SUB_PORT_GIVEN="${SUB_PORT:-}"') + line_of(H, 'SUB_PORT="${SUB_PORT:-8444}"') + \
        line_of(H, '_SUB_BIND_GIVEN="${SUB_BIND:-}"') + line_of(H, 'SUB_BIND="${SUB_BIND:-0.0.0.0}"')
READ = line_of(H, "SUB_PORT_SAVED=\"$(sed -n 's/^SUB_PORT=//p'") + line_of(H, "SUB_BIND_SAVED=\"$(sed -n 's/^SUB_BIND=//p'")
UNITFB = line_of(H, "[ -z \"$SUB_PORT_SAVED\" ] && SUB_PORT_SAVED=\"$(sed -n 's/^Environment=SWG_SUB_PORT=//p' /etc/systemd/system/swg-sub.service")
RESTORE = span(H, '# ⚠️ …AND THE SUBSCRIPTION ADDRESS IT WAS INSTALLED WITH.', 'if [ -z "$_SUB_BIND_GIVEN" ] && [ -n "$SUB_BIND_SAVED" ]; then SUB_BIND="$SUB_BIND_SAVED"; fi\n')
VPORT = line_of(H, "v_port(){")
def reinstall(conf, unit_port=None, env=None):
    d = tempfile.mkdtemp(prefix="sp-"); open(os.path.join(d, "install.conf"), "w").write(conf)
    unitf = os.path.join(d, "swg-sub.service")
    if unit_port:
        open(unitf, "w").write("[Service]\nEnvironment=SWG_SUB_HOST=0.0.0.0\nEnvironment=SWG_SUB_PORT=%s\n" % unit_port)
    script = (VPORT + GIVEN + 'ETC_DIR=%s; SUB_PORT_SAVED=""; SUB_BIND_SAVED=""\n%s%s%s'
              'echo "SUB=$SUB_BIND:$SUB_PORT"\n') % (d, READ, UNITFB.replace("/etc/systemd/system/swg-sub.service", unitf), RESTORE)
    e = {k: v for k, v in os.environ.items() if k not in ("SUB_PORT", "SUB_BIND")}; e.update(env or {})
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], capture_output=True, text=True, env=e, timeout=60)
    return r.returncode, r.stdout + r.stderr
rc, out = reinstall("SUB_PORT=8446\nSUB_BIND=\n")
check("[1] the kept install.conf's SUB_PORT is the re-install's", rc == 0 and "SUB=0.0.0.0:8446" in out, (rc, out))
rc, out = reinstall("SUB_PORT=8446\n", env={"SUB_PORT": "9000"})
check("[1] …a given SUB_PORT wins", rc == 0 and "SUB=0.0.0.0:9000" in out, (rc, out))
rc, out = reinstall("PORT=2087\n", unit_port="8447")
check("[1] …with none in install.conf, swg-sub's unit's port", rc == 0 and "SUB=0.0.0.0:8447" in out, (rc, out))
rc, out = reinstall("SUB_PORT=8446\nSUB_BIND=10.0.0.5\n")
check("[1] a SUB_BIND given once (install.conf keeps it) is kept", rc == 0 and "SUB=10.0.0.5:8446" in out, (rc, out))
rc, out = reinstall("PORT=2087\n")
check("[1] …no SUB_PORT in install.conf and no swg-sub unit: the default, and the run goes on (set -e)",
      rc == 0 and "SUB=0.0.0.0:8444" in out, (rc, out))
rc, out = reinstall("SUB_PORT=abc\n")
check("[1] …a port that is not one is not taken", rc == 0 and "SUB=0.0.0.0:8444" in out, (rc, out))
check("[1] install.conf keeps SUB_PORT, and SUB_BIND only as given (or kept from a given one)",
      "\nSUB_PORT=${SUB_PORT}\nSUB_BIND=${_SUB_BIND_GIVEN:-${SUB_BIND_SAVED:-}}\n" in H)

print("\n[2] install-host.sh: a changed unit restarts a running swg-sub")
SUBBLK = span(H, 'if [ -f "$PREFIX$SUB_DIR/swg-sub" ]; then   # inert until enabled in Settings → Subscriptions\n', "\n  fi\nfi\n")
def sub_block(was_up, change, panel_up=True, defer=""):
    d = tempfile.mkdtemp(prefix="sp-u-"); os.makedirs(os.path.join(d, "opt/swg-sub")); os.makedirs(os.path.join(d, "etc/systemd/system"))
    open(os.path.join(d, "opt/swg-sub/swg-sub"), "w").write("")
    unit = os.path.join(d, "etc/systemd/system/swg-sub.service"); open(unit, "w").write("OLD\n")
    log = os.path.join(d, "log")
    stub = tempfile.mkdtemp(prefix="sp-s-")
    open(os.path.join(stub, "systemctl"), "w").write(
        '#!/bin/bash\necho "systemctl $*" >> %s\n'
        'case "$*" in "is-active --quiet swg-sub") exit %d;; "is-active --quiet swg-panel-server") exit %d;; esac\nexit 0\n'
        % (log, 0 if was_up else 3, 0 if panel_up else 3))
    os.chmod(os.path.join(stub, "systemctl"), 0o755)
    script = ('PREFIX=%s; SUB_DIR=/opt/swg-sub; DRYRUN=false; _NOW=--now; SUB_BIND=0.0.0.0; SUB_PORT=8446; SWG_DEFER_START="%s"\n'
              'run(){ "$@"; }; ok(){ echo "OK $*"; }; warn(){ echo "WARN $*"; }; sub(){ echo "SUB $*"; }\n'
              'write_sub_unit(){ printf "%s" > "$PREFIX/etc/systemd/system/swg-sub.service"; }\n%s'
              % (d, defer, "NEW\\n" if change else "OLD\\n", SUBBLK))
    rc, out = bash(script, {"PATH": stub + ":" + os.environ["PATH"]})
    return rc, out, open(log).read() if os.path.exists(log) else ""
rc, out, log = sub_block(True, True)
check("[2] a changed unit restarts a running swg-sub", rc == 0 and "systemctl restart swg-sub" in log and "restarted — its unit changed" in out, (rc, out, log))
check("[2] …and then a running panel is restarted, to record swg-sub's new address",
      "systemctl restart swg-panel-server" in log and log.index("restart swg-sub") < log.index("restart swg-panel-server")
      and "record swg-sub's new address" in out, (out, log))
rc, out, log = sub_block(True, True, panel_up=False)
check("[2] …a panel that is not running is left so", rc == 0 and "restart swg-panel-server" not in log, (rc, log))
rc, out, log = sub_block(True, True, defer="1")
check("[2] …nor during a convert's deferred start (the convert starts the panel at the switch)", rc == 0 and "restart swg-panel-server" not in log, (rc, log))
rc, out, log = sub_block(True, False)
check("[2] …an unchanged unit: no restart", rc == 0 and "restart swg-sub" not in log, (rc, out, log))
rc, out, log = sub_block(False, True)
check("[2] …a stopped swg-sub: `enable --now` starts it on the new unit, no extra restart",
      rc == 0 and "enable --quiet --now swg-sub" in log and "restart swg-sub" not in log, (rc, out, log))

print("\n[3] the panel: the URL follows a port that moves")
P = SRC["PANEL"]
mod = ast.parse(P)
seg = {n.name: ast.get_source_segment(P, n) for n in mod.body if isinstance(n, ast.FunctionDef)}
def assign(name):
    return next(ast.get_source_segment(P, n) for n in mod.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
LIFT = "\n".join(assign(n) for n in ("PANEL_SETTINGS_DEFAULTS", "SUB_UNIT_FILE", "SUB_DROPIN_FILE", "_NETCTL_DROPIN_MARK")) + "\n\n" + \
    "\n\n".join(seg[n] for n in ("_is_loopback", "_sub_bind_of", "_sub_bind_in", "_sub_bind_chosen", "_sub_url_port",
                                 "_sub_url_on_port", "_record_sub_bind", "_flag_sub_url_port", "_reconcile_sub_listen_at_boot"))
def panel_ns(active="active"):
    import ipaddress
    ns = {"os": os, "re": re, "json": json, "contextlib": contextlib, "ipaddress": ipaddress, "urlparse": urlparse, "socket": socket,
          "IN_DOCKER": False, "PANEL_DECLARATIVE": False, "_SUB_LIVE_BIND": {}, "VK_POOL_PER_USER_DEFAULT": 3,
          "panel_service_health": lambda ttl=20: {"sub": {"present": True, "active": active}}}
    ns["EV"], ns["Q"], ns["SAVED"] = [], [], []
    ns["ev_append"] = lambda rp, kind, ident, verb, name, detail="", **k: ns["EV"].append((kind, ident, verb, name, detail))
    ns["_netctl_enqueue"] = lambda deps, verb, args: ns["Q"].append((verb, list(args))) or True
    ns["save_critical"] = lambda p, text: ns["SAVED"].append(json.loads(text))
    ns["write_sub_serve"] = lambda deps, base_alt="": None
    exec(compile(LIFT, "swg-panel-server(extract)", "exec"), ns)
    return ns
def record(url, old_port, new_port):
    ns = panel_ns()
    ps = json.loads(json.dumps(ns["PANEL_SETTINGS_DEFAULTS"]))
    ps["access"]["sub"].update({"url": url, "host": "0.0.0.0", "port": old_port})
    deps = {"roster_path": "/nonexistent/users.json", "panel_settings": ps, "panel_settings_path": "/nonexistent/ps.json"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ns["_record_sub_bind"](deps, ps, ("0.0.0.0", str(new_port)), "where swg-sub listens, as installed")
    return ps["access"]["sub"]["url"], out.getvalue(), ns["EV"]
url, log, ev = record("https://192.168.77.5:8446", 8446, 8444)
check("[3] a URL naming the old port follows the recorded one", url == "https://192.168.77.5:8444"
      and "names 8444 now" in log and ev and ev[0][2] == "Moved the subscription URL to swg-sub's port", (url, log, ev))
url, log, ev = record("https://[2001:db8::5]:8446/subs", 8446, 8444)
check("[3] …an IPv6 literal and a path are kept", url == "https://[2001:db8::5]:8444/subs", url)
url, log, ev = record("sub.example.net:8446", 8446, 8444)
check("[3] …a URL typed without a scheme keeps having none", url == "sub.example.net:8444", url)
url, log, ev = record("https://sub.example.net", 8446, 8444)
check("[3] a URL with no port stays (443 is not swg-sub's)", url == "https://sub.example.net" and not ev, (url, ev))
url, log, ev = record("https://sub.example.net:8443", 8446, 8444)
check("[3] a URL naming another port (a reverse proxy's) stays", url == "https://sub.example.net:8443" and not ev, (url, ev))

print("\n[4] the panel: a URL naming a dead port is flagged")
def flag(url, listen_port):
    ns = panel_ns()
    ps = {"access": {"sub": {"url": url}}}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = ns["_flag_sub_url_port"]({"roster_path": "/nonexistent"}, ps, listen_port)
    return r, out.getvalue(), ns["EV"]
s0 = socket.socket(); s0.bind(("127.0.0.1", 0)); dead = s0.getsockname()[1]; s0.close()   # a port nothing answers on
r, log, ev = flag("https://192.168.77.5:%d" % dead, 8444)
check("[4] a URL naming a port nothing answers on is flagged", r and ("names port %d, where nothing on this box listens" % dead) in log
      and "Settings → Panel access → Subscription address" in log and ev and ev[0][2] == "The subscription URL names a port nothing listens on",
      (r, log, ev))
lsn = socket.socket(); lsn.bind(("127.0.0.1", 0)); lsn.listen(1); live = lsn.getsockname()[1]
r, log, ev = flag("https://sub.example.net:%d" % live, 8444)
lsn.close()
check("[4] …a port something answers on (a reverse proxy) is not", not r and not ev, (r, log))
check("[4] …nor swg-sub's own port, nor 443", not flag("https://h:8444", 8444)[0] and not flag("https://h", 8444)[0]
      and not flag("https://h:443", 8444)[0])
# once per case: the same panel started again and again
st = tempfile.mkdtemp(prefix="sp-f-")
ns1 = panel_ns()
deps1 = {"roster_path": os.path.join(st, "users.json"), "nodes_path": os.path.join(st, "nodes.json")}
def start(url, lp):
    with contextlib.redirect_stdout(io.StringIO()) as o:
        r = ns1["_flag_sub_url_port"](deps1, {"access": {"sub": {"url": url}}}, lp)
    return r, o.getvalue()
dead_url = "https://192.168.77.5:%d" % dead
logs = [start(dead_url, 8444)[1] for _ in range(4)]
check("[4] …the log at every start, the activity list ONE row per case (4 starts, 1 row)",
      all("where nothing on this box listens" in l for l in logs) and len(ns1["EV"]) == 1, (len(ns1["EV"]), logs[:1]))
start(dead_url, 8445)
check("[4] …a new case (swg-sub moved again) adds its row", len(ns1["EV"]) == 2 and ns1["EV"][-1][4] == "%d ≠ 8445" % dead, ns1["EV"])
start("https://192.168.77.5:8445", 8445); start(dead_url, 8445)
check("[4] …a case that resolved and comes back adds one again", len(ns1["EV"]) == 3, ns1["EV"])
start("https://192.168.77.5:8445", 8445)
check("[4] …and the note goes once the URL is right", not os.path.exists(os.path.join(st, "sub-url-flag")), os.listdir(st))

print("\n[5] the panel's start: a stopped swg-sub stays stopped")
FOOT = "# managed by swg-netctl — from the panel's Access & TLS settings; do not edit by hand\n[Service]\nEnvironment=SWG_SUB_HOST=0.0.0.0\nEnvironment=SWG_SUB_PORT=8444\n"
def boot(active, chosen=False):
    ns = panel_ns(active)
    d = tempfile.mkdtemp(prefix="sp-b-")
    ns["SUB_UNIT_FILE"] = os.path.join(d, "swg-sub.service"); ns["SUB_DROPIN_FILE"] = os.path.join(d, "10-access.conf")
    open(ns["SUB_UNIT_FILE"], "w").write("[Service]\nEnvironment=SWG_SUB_HOST=127.0.0.1\nEnvironment=SWG_SUB_PORT=%s\n" % ("8444" if not chosen else "8444"))
    if not chosen:
        open(ns["SUB_DROPIN_FILE"], "w").write(FOOT)
    ps = json.loads(json.dumps(ns["PANEL_SETTINGS_DEFAULTS"]))
    if chosen:
        ps["access"]["sub"].update({"host": "0.0.0.0", "port": 8446}); ps["sub_bind_by"] = "operator"
    deps = {"roster_path": "/nonexistent/users.json", "panel_settings": ps, "panel_settings_path": "/nonexistent/ps.json"}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ns["_reconcile_sub_listen_at_boot"](deps)
    return ns["Q"], out.getvalue()
q, log = boot("inactive")
check("[5] the footprint heal: a stopped swg-sub is set right, not restarted",
      q == [("set-listen", ["sub", "127.0.0.1", "8444"])] and "stopped, and it stays stopped" in log and "was listening" not in log, (q, log))
q, log = boot("active")
check("[5] …a running one is set right and restarted, and the line says it was listening",
      q == [("set-listen", ["sub", "127.0.0.1", "8444"]), ("restart", ["sub"])] and "swg-sub was listening on 0.0.0.0:8444" in log, (q, log))
q, log = boot("inactive", chosen=True)
check("[5] the operator's address re-asserted: set for a stopped swg-sub, not restarted",
      q == [("set-listen", ["sub", "0.0.0.0", "8446"])] and "stays stopped" in log, (q, log))
q, log = boot("active", chosen=True)
check("[5] …and a running one restarted onto it", q == [("set-listen", ["sub", "0.0.0.0", "8446"]), ("restart", ["sub"])] and "(it ran on" in log, (q, log))

print("\n[6] update.sh, and a Docker re-install")
UP = SRC["UPDATE"]
blk = UP[UP.index('      if bare_panel_parked; then   # its panel is parked (guard_second_panel), and it is parked with it\n'):]
blk = blk[:blk.index("\n      fi\n") + 9]
i_chk = blk.find('      elif ! $DRYRUN && ! systemctl is-active --quiet swg-sub 2>/dev/null; then\n')
i_rst = blk.find("run systemctl restart swg-sub")
check("[6] update.sh restarts swg-sub only when it runs", 0 < i_chk < i_rst and "left stopped, as it was" in blk, blk)
# ensure_sub_server (update.sh's heal), driven: an operator's disable holds; one running off the boot list is enabled
def esi(enabled, active):
    d = tempfile.mkdtemp(prefix="sp-e-"); os.makedirs(os.path.join(d, "opt/swg-sub"))
    open(os.path.join(d, "opt/swg-sub/swg-sub"), "w").write(""); unit = os.path.join(d, "swg-sub.service"); open(unit, "w").write("[Service]\n")
    log = os.path.join(d, "log"); stub = tempfile.mkdtemp(prefix="sp-es-")
    open(os.path.join(stub, "systemctl"), "w").write(
        '#!/bin/bash\necho "systemctl $*" >> %s\ncase "$*" in "is-enabled --quiet swg-sub") exit %d;; "is-active --quiet swg-sub") exit %d;; esac\nexit 0\n'
        % (log, 0 if enabled else 1, 0 if active else 3))
    os.chmod(os.path.join(stub, "systemctl"), 0o755)
    fn = UP[UP.index("ensure_sub_server(){"):]
    fn = fn[:fn.index("\n}\n") + 3]
    script = ('DRYRUN=false; SRC=%s/opt/swg-sub; SUB_DIR=%s/opt/swg-sub; SUB_WEB=""\n'
              'info(){ :; }; ok(){ :; }; warn(){ :; }; bare_panel_parked(){ return 1; }; id(){ return 0; }\n%s'
              'ensure_sub_server\n') % (d, d, fn.replace("local unit=/etc/systemd/system/swg-sub.service", "local unit=%s" % unit))
    rc, out = bash(script, {"PATH": stub + ":" + os.environ["PATH"]})
    return rc, out, open(log).read() if os.path.exists(log) else ""
rc, out, log = esi(enabled=False, active=False)
check("[6] ensure_sub_server leaves a disabled, stopped swg-sub disabled (the operator's `disable --now`)",
      rc == 0 and "enable" not in log.replace("is-enabled", ""), (rc, out, log))
rc, out, log = esi(enabled=False, active=True)
check("[6] …and enables one that runs off the boot list", rc == 0 and "systemctl enable --quiet swg-sub" in log, (rc, out, log))
D = SRC["DOCKER"]
keys = D[D.index('  for _k in PANEL_URL NODE_TOKEN NODE_ENDPOINT PANEL_USER PANEL_PASSWORD PANEL_DOMAIN PANEL_PORT PANEL_BASE \\\n'):]
keys = keys[:keys.index("; do")]
check("[6] a Docker re-install keeps SUB_PORT and SUB_BIND from its .env", " SUB_PORT " in keys and " SUB_BIND " in keys, keys)

print()
if FAILS:
    print("FAIL (%d): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL PASS")
