#!/usr/bin/env python3
"""Self-test: an uninstall that is typed wrong is not an install, and a master's node finds its panel's own door again.

Client report 2026-11-07, two defects on one Docker master:

  * `bootstrap.sh -- uninstal` (a word a phone's copy and paste had changed) ran a full RE-INSTALL: every word the
    script did not know went to the installer, which ignores what it does not read. `bash -c "$(curl …)" uninstall`
    without the `--` did the same — bash took the word as the script's NAME ($0), and the run had no arguments.
  * the master's node synced to http://127.0.0.1:80 for good — a local heal had moved it off the panel's loopback door
    (8088) while the panel was down for the re-install, and saved that (data/node/panel-url, which outranks the .env).
    No heal could bring it back: 8088 is in no list of common ports.

  [1] bootstrap.sh's words: update / uninstall (and --update / --uninstall) are the action; a word after `bash -c`
      that bash took as the script's name is read as the first argument, said in one line; a word it does not know is
      refused before anything runs — a hidden character shown, a near word named, a flag near update/uninstall refused too; a flag's value is passed on; the
      switches take none; a file run and a bare `bash -c` (no arguments) unchanged
  [2] swg-noded's local heal probes the configured loopback address (SWG_PANEL_URL_CONFIGURED) first, then the panel's
      local port (access.panel.local_port), then the common ports as before; a non-loopback configured address, or the
      one already failing, is not probed first; the re-point is saved
  [3] docker/node-entrypoint.sh keeps the configured address before a learned one replaces it, and exports it

Run: python3 tests/master_node_heal_selftest.py            (0 = pass)
     --plant <passall|noarg0|nofirst|nolocal|noexport|nearflag>   one old behaviour back → RED (exit 0 when caught)
     --perturb                                               them all → RED
"""
import importlib.machinery, importlib.util, io, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTS_ALL = ("passall", "noarg0", "nofirst", "nolocal", "noexport", "nearflag")
PLANTS = set(PLANTS_ALL) if "--perturb" in sys.argv else (
    {sys.argv[sys.argv.index("--plant") + 1]} if "--plant" in sys.argv else set())
assert PLANTS <= set(PLANTS_ALL), "unknown plant"
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def src(f):
    return open(os.path.join(ROOT, f), encoding="utf-8").read()


def plant(s, a, b):
    assert s.count(a) == 1, "plant anchor missing or not unique — this run would FALSE-PASS: %r" % a[:80]
    return s.replace(a, b, 1)


BS, NODED, EP = src("bootstrap.sh"), src("swg-noded"), src("docker/node-entrypoint.sh")
if "passall" in PLANTS:    # every word passed on, as shipped
    BS = plant(BS, '[ "$_bs_val" = yes ] || _bs_unknown "$1"; PASS+=', 'PASS+=')
if "nearflag" in PLANTS:   # a flag near update/uninstall passed on, as shipped
    BS = plant(BS, '    -upda*|--upda*|-unin*|--unin*) _bs_unknown "$1";;', '')
if "noarg0" in PLANTS:     # the word bash took as $0 left there
    BS = plant(BS, '*) _SWG_ARG0="$0"; set -- "$0" "$@";; esac', '*) ;; esac')
if "nofirst" in PLANTS:    # the configured address not probed
    NODED = plant(NODED, '                firsts.append(cfg)\n', '                pass\n')
if "nolocal" in PLANTS:    # the panel's local port not probed
    NODED = plant(NODED, '                    firsts.append("http://%s:%d" % ("[%s]" % host if ":" in host else host, lp))\n',
                  '                    pass\n')
if "noexport" in PLANTS:   # the configured address not kept
    EP = plant(EP, 'SWG_PANEL_URL_CONFIGURED="$PANEL_URL"\n', '')

# ── [1] bootstrap.sh's words ───────────────────────────────────────────────────────────────────────────────────────
END = '\n[ "$METHOD" = bare-metal ] && METHOD=baremetal\n'   # at the line start: an indented twin sits further down
assert BS.count(END) == 1, "the parse's end is not where this gate reads it — this run would FALSE-PASS"
PARSE = BS[:BS.index(END) + len(END)] + (
    'declare -p ACTION METHOD ROLE ON_CONFLICT\nprintf "PASS=%s\\n" "${PASS[*]-}"\nexit 0\n}\n')
T = tempfile.mkdtemp(prefix="masterheal-")
PF = os.path.join(T, "bootstrap-parse.sh")
open(PF, "w", encoding="utf-8").write(PARSE)
ENV = dict(os.environ, NO_COLOR="1")


def parse(args, filemode=False):
    cmd = ["bash", PF] + args if filemode else ["bash", "-c", PARSE] + args
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=ENV, cwd=T, timeout=30)
    v = dict(re.findall(r'declare -- (\w+)="([^"]*)"', p.stdout))
    m = re.search(r"^PASS=(.*)$", p.stdout, re.M)
    v["PASS"] = m.group(1) if m else None
    return p.returncode, v, p.stdout + p.stderr


for args, want in (
        (["--", "uninstall"], "uninstall"),
        (["--", "update", "-y", "--no-components"], "update"),
        (["--", "--uninstall"], "uninstall"),
        (["--", "-update"], "update")):
    rc, v, out = parse(args)
    check("[1] %s → the action %s" % (" ".join(args), want), rc == 0 and v.get("ACTION") == want, (rc, v, out[-300:]))
rc, v, out = parse(["uninstall", "--dry-run"])
check("[1] `bash -c … uninstall` (no --): the word bash took as the script's name is the action",
      rc == 0 and v.get("ACTION") == "uninstall" and v.get("PASS") == "--dry-run", (rc, v, out[-300:]))
check("[1] …said in one line", out.count("bash took it as the script's name") == 1, out[-300:])
rc, v, out = parse(["--uninstall"])
check("[1] `bash -c … --uninstall` (no --): the same", rc == 0 and v.get("ACTION") == "uninstall", (rc, v, out[-300:]))
for args, why in ((["--", "uninstal"], "a near word"), (["--", "uninstal\nl"], "a line break inside it"),
                  (["--", "unin​stall"], "a zero-width space inside it"), (["--", "--yes", "uninstal"], "after a switch"),
                  (["--", "docker", "reinstall"], "after a command word"), (["--", "--uninstal"], "a near flag"),
                  (["--", "-updates", "-y"], "a near flag, one dash")):
    rc, v, out = parse(args)
    check("[1] refused, nothing run: %s (%r)" % (why, args[-1]),
          rc != 0 and "unknown command" in out and "nothing was done" in out and "ACTION" not in v, (rc, out[-300:]))
rc, v, out = parse(["--", "uninstal"])
check("[1] …a near word is named", "Did you mean 'uninstall'?" in out, out[-300:])
rc, v, out = parse(["--", "--uninstal"])
check("[1] …a near flag too", "Did you mean 'uninstall'?" in out, out[-300:])
rc, v, out = parse(["--", "unin​stall"])
check("[1] …a hidden character is shown", "$'unin\\342\\200\\213stall'" in out and "type the word by hand" in out, out[-400:])
rc, v, out = parse(["--", "docker", "host", "-pass", "s3cret", "-domain", "vpn.example.com", "--yes", "--dry-run"])
check("[1] a flag's value is passed on, a switch takes none",
      rc == 0 and (v.get("METHOD"), v.get("ROLE"), v.get("PASS")) == ("docker", "host", "-pass s3cret -domain vpn.example.com --yes --dry-run"),
      (rc, v, out[-300:]))
rc, v, out = parse(["--", "docker", "host-node"])
check("[1] the Docker installer's older name for master is passed on", rc == 0 and v.get("PASS") == "host-node", (rc, v))
rc, v, out = parse(["--", "-key", "abc", "-host", "https://p.example", "node"])
check("[1] -key / -host take their value here, the role word stays a role",
      rc == 0 and (v.get("ROLE"), v.get("PASS")) == ("node", ""), (rc, v))
rc, v, out = parse([])
check("[1] a bare `bash -c` (no arguments) is an install, as before",
      rc == 0 and (v.get("ACTION"), v.get("PASS")) == ("", "") and "script's name" not in out, (rc, v, out[-300:]))
rc, v, out = parse(["uninstall"], filemode=True)
check("[1] a file run reads its arguments as before", rc == 0 and v.get("ACTION") == "uninstall" and "script's name" not in out,
      (rc, v, out[-300:]))

# ── [2] swg-noded's local heal ─────────────────────────────────────────────────────────────────────────────────────
NP = os.path.join(T, "swg-noded")
open(NP, "w", encoding="utf-8").write(NODED)
ld = importlib.machinery.SourceFileLoader("swgnoded_masterheal", NP)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_masterheal", ld))
try:
    ld.exec_module(N)
except SystemExit:
    pass
N.STATE_DIR = os.path.join(T, "state")
os.makedirs(N.STATE_DIR, exist_ok=True)
N._persist_config = lambda cfg: None
N.log = lambda *a, **k: None
SETTINGS = {}
_real_open = open


def _open(path, *a, **k):
    if isinstance(path, str) and path in SETTINGS:
        return io.StringIO(SETTINGS[path])
    if isinstance(path, str) and path.startswith(("/var/lib/swg-panel/", "/etc/swg-panel/")):
        raise FileNotFoundError(path)
    return _real_open(path, *a, **k)


N.open = _open


def heal(cur, live, configured=None, local_port=None):
    PROBES[:] = []
    SETTINGS.clear()
    if local_port is not None:
        SETTINGS["/var/lib/swg-panel/panel-settings.json"] = json.dumps(
            {"access": {"panel": {"port": 443, "local_port": local_port}}})
    os.environ.pop("SWG_PANEL_URL_CONFIGURED", None)
    if configured is not None:
        os.environ["SWG_PANEL_URL_CONFIGURED"] = configured
    with __import__("contextlib").suppress(OSError):
        os.remove(os.path.join(N.STATE_DIR, "panel-url"))
    N._LOCAL_HEAL["at"] = 0.0
    N._verify_panel = lambda url, tok, panel: (PROBES.append(url.rstrip("/")), url.rstrip("/") in live)[1]
    panel = {"url": cur, "token": "tok"}
    r = N._heal_local_panel(panel, {"panel": dict(panel)})
    try:
        saved = _real_open(os.path.join(N.STATE_DIR, "panel-url")).read().strip()
    except OSError:
        saved = None
    return r, panel["url"], saved


PROBES = []
r, url, saved = heal("http://127.0.0.1:80", {"http://127.0.0.1:8088"}, configured="http://127.0.0.1:8088")
check("[2] the client's box: stranded on :80, the configured :8088 answers → back on it, saved",
      (r, url, saved) == ("http://127.0.0.1:8088/api/node/sync", "http://127.0.0.1:8088", "http://127.0.0.1:8088"), (r, url, saved, PROBES))
check("[2] …the configured address is the first probe", PROBES[:1] == ["http://127.0.0.1:8088"], PROBES[:4])
r, url, saved = heal("http://127.0.0.1:80", {"http://127.0.0.1:8089"}, local_port=8089)
check("[2] no configured address (bare metal): the panel's local port, at the root, over plain HTTP",
      (r, url) == ("http://127.0.0.1:8089/api/node/sync", "http://127.0.0.1:8089") and PROBES[:1] == ["http://127.0.0.1:8089"],
      (r, url, PROBES[:4]))
r, url, saved = heal("http://127.0.0.1:80", {"http://127.0.0.1:8088"}, configured="http://127.0.0.1:8088", local_port=8088)
check("[2] the same door named twice is probed once", PROBES.count("http://127.0.0.1:8088") == 1 and r, PROBES)
r, url, saved = heal("http://127.0.0.1:80", set(), configured="https://panel.example.com")
check("[2] a configured address off loopback is not probed (a new trust is the sync's to decide, not this heal's)",
      r is None and not any("panel.example.com" in p for p in PROBES), PROBES[:4])
r, url, saved = heal("http://127.0.0.1:8088", set(), configured="http://127.0.0.1:8088")
check("[2] the address already failing is not probed again first", "http://127.0.0.1:8088" not in PROBES, PROBES[:4])
r, url, saved = heal("https://127.0.0.1:443", {"https://127.0.0.1:8443"})
check("[2] nothing configured, no settings: the common ports as before, the re-point saved",
      PROBES[:1] == ["https://127.0.0.1:8443"] and (r, saved) == ("https://127.0.0.1:8443/api/node/sync", "https://127.0.0.1:8443"),
      (r, saved, PROBES[:4]))
r, url, saved = heal("https://panel.example.com", {"http://127.0.0.1:8088"}, configured="http://127.0.0.1:8088")
check("[2] a node that syncs off loopback never heals locally", r is None and PROBES == [], (r, PROBES))

# ── [3] the entrypoint keeps the configured address ────────────────────────────────────────────────────────────────
a = EP.index(': "${PANEL_URL:?')
b = EP.index("if [ -f /var/lib/swg-noded/panel-token ]")
SD = os.path.join(T, "noded-state")
os.makedirs(SD, exist_ok=True)
open(os.path.join(SD, "panel-url"), "w").write("http://127.0.0.1:80\n")
head = EP[a:b].replace("/var/lib/swg-noded", SD).replace("/etc/swg-agent", SD + "/agent").replace("/etc/amnezia/amneziawg", SD + "/awg")
exp = re.search(r"^export SWG_AGENT_CONFIG=.*$", EP, re.M)
check("[3] the export line carries it", bool(exp) and "SWG_PANEL_URL_CONFIGURED" in exp.group(0).split(), exp and exp.group(0))
p = subprocess.run(["sh", "-c", 'set -eu\nlog(){ :; }\n%s\n%s\nenv | grep -E "^(PANEL_URL|SWG_PANEL_URL_CONFIGURED)=" | sort'
                    % (head, "export PANEL_URL " + (exp.group(0).split(None, 1)[1] if exp else ""))],
                   capture_output=True, text=True, env={k: v for k, v in dict(os.environ, PANEL_URL="http://127.0.0.1:8088", NODE_TOKEN="tok", NODE_ENDPOINT="192.0.2.1").items()
                        if k != "SWG_PANEL_URL_CONFIGURED"}, timeout=30)   # [2] set it here: the shell must not inherit it
check("[3] the learned :80 still runs the node, the configured :8088 travels beside it",
      p.returncode == 0 and p.stdout.split() == ["PANEL_URL=http://127.0.0.1:80", "SWG_PANEL_URL_CONFIGURED=http://127.0.0.1:8088"],
      (p.returncode, p.stdout, p.stderr[-200:]))

print()
if PLANTS:
    print("PERTURBED (%s): %s" % (",".join(sorted(PLANTS)),
                                  "RED as expected (%d failing)" % len(FAILS) if FAILS else "STILL GREEN — the gate does not see the defect"))
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
