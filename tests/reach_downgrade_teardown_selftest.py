#!/usr/bin/env python3
"""Self-test — when an OLDER swg-noded starts, the device-access tables go; when a capable one starts, they stay.

`reconcile_dev_reach` removes `swg_reach` as soon as the panel sends no plan — but that code lives in the binary a
downgrade REPLACES. Start a build that predates device access and nothing can touch the table again (the panel stops
sending `dev_reach` to a node reporting `net_deps.reach < 2`): the last policy is frozen, and it goes on dropping what
the panel has since allowed. Measured on msk-main (1.8.7 qualification S9): downgraded with `bootstrap.sh update`
SWG_REF=main, `swg_reach` + `swg_share` stayed; the interface set to Everyone, a neighbour's probe still died, the
frozen table's own drop counter rising.

⚠️ This sweep first lived in update.sh, before the binary copy — and never ran. `bootstrap.sh update` runs the update.sh
of the ref it was asked for, so a downgrade is always performed by the OLDER script. It now runs as the swg-noded unit's
ExecStartPre, from a drop-in the older release's update.sh leaves alone (it heals the unit only when it is MISSING and
never touches `swg-noded.service.d/`).

  [1] every place that writes the swg-noded unit writes the drop-in; update.sh heals it; uninstall and the bare→docker
      teardown remove it; and the dead pre-copy sweep is gone from update.sh
  [2] BEHAVIOURAL — the rendered drop-in, unescaped the way systemd does ($$ → $), run by /bin/sh with a fake nft:
      · an older build is starting   → both tables deleted
      · a capable build is starting  → nft never asked to delete anything (no unenforced window on a restart/upgrade)
      · only one table installed      → only that one deleted
      · no nft on the box             → exit 0, nothing attempted
      · every outcome exits 0, and the line carries `-`, so a sweep can never keep swg-noded from starting
  [3] ensure_noded_reach_sweep: writes beside an existing unit only; rewrites stale content; idempotent; a dry run writes nothing
  [4] the capability the drop-in greps for is really defined in swg-noded — a rename would make EVERY start sweep

Run: python3 tests/reach_downgrade_teardown_selftest.py     (0 = pass)
     --perturb            every build looks capable, so the sweep never runs     → RED on [2]
     --perturb-escape     `$t` instead of `$$t` (systemd expands it to nothing)  → RED on [2]
     --perturb-uninstall  uninstall leaves the drop-in directory behind          → RED on [1]
     --perturb-heal       update.sh no longer heals the drop-in                   → RED on [1]
"""
import os, re, shlex, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODE = "capable" if "--perturb" in sys.argv else next((a[len("--perturb-"):] for a in sys.argv[1:] if a.startswith("--perturb-")), "")
FAILS = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — %s" % (detail,)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def src(name):
    return open(os.path.join(ROOT, name), encoding="utf-8").read()


lib, upd, uni = src("lib/common.sh"), src("update.sh"), src("uninstall.sh")
inode, ihost, noded = src("install-node.sh"), src("install-host.sh"), src("swg-noded")
PLANTS = {
    "capable": ("lib", '''ExecStartPre=-/bin/sh -c 'grep -q "^def _reach_drop_table" ${1}/swg-noded 2>/dev/null && exit 0;''',
                '''ExecStartPre=-/bin/sh -c 'true && exit 0;'''),
    "escape": ("lib", r"nft list table inet \$\$t >/dev/null 2>&1 || continue; nft delete table inet \$\$t",
               r"nft list table inet \$t >/dev/null 2>&1 || continue; nft delete table inet \$t"),
    "uninstall": ("uni", "rmrf $SD/swg-noded.service $SD/swg-noded.service.d; run systemctl daemon-reload",
                  "rmrf $SD/swg-noded.service; run systemctl daemon-reload"),
    "heal": ("upd", '  ensure_noded_reach_sweep "$NODED_DIR"', "  :"),
}
if MODE:
    where, frm, to = PLANTS[MODE]
    text = {"lib": lib, "uni": uni, "upd": upd}[where]
    assert text.count(frm) == 1, "perturbation anchor missing (%s) — this run would FALSE-PASS" % MODE
    text = text.replace(frm, to, 1)
    if where == "lib":
        lib = text
    elif where == "uni":
        uni = text
    else:
        upd = text

T = tempfile.mkdtemp(prefix="reachsweep-")
LIB = T + "/common.sh"
open(LIB, "w").write(lib)

print("\n[1] written wherever the unit is, healed on update, removed with the node")
UNIT_WRITE = 'writef /etc/systemd/system/swg-noded.service 644'
DROP_WRITE = 'noded_reach_sweep_dropin "$NODED_DIR" | writef "/etc/systemd/system/$NODED_REACH_SWEEP_DROPIN" 644'
for label, text in (("install-node.sh", inode), ("install-host.sh (master)", ihost)):
    u, d = text.find(UNIT_WRITE), text.find(DROP_WRITE)
    check("%s writes the drop-in after the unit" % label, 0 <= u < d, (u, d))
check("the drop-in lives under swg-noded.service.d/, not in the unit an older update.sh may recreate",
      re.search(r"^NODED_REACH_SWEEP_DROPIN=swg-noded\.service\.d/[\w.-]+\.conf$", lib, re.M) is not None)
check("update.sh heals it in the bare-metal node block", 'ensure_noded_reach_sweep "$NODED_DIR"' in upd)
check("uninstall.sh removes the drop-in directory with the unit", "rmrf $SD/swg-noded.service $SD/swg-noded.service.d;" in uni)
check("the bare→docker teardown removes it too", "rm -rf /etc/systemd/system/swg-noded.service /etc/systemd/system/swg-noded.service.d;" in lib)
check("⚠️ the pre-copy sweep that could never run is gone from update.sh", "reach_tables_drop_if_unsupported" not in upd + lib)

print("\n[2] the drop-in, as systemd will run it")
rendered = subprocess.run(["bash", "-c", '. "$1" >/dev/null 2>&1; noded_reach_sweep_dropin /opt/swg-noded', "x", LIB],
                          capture_output=True, text=True).stdout
line = next((l for l in rendered.splitlines() if l.startswith("ExecStartPre=")), "")
check("the drop-in renders one ExecStartPre", bool(line), rendered[:200])
val = line[len("ExecStartPre="):]
check("…prefixed `-`: a failed sweep never blocks the start", val.startswith("-"), val[:20])
cmd = shlex.split(val.lstrip("-@:+!").replace("$$", "\0").replace("%%", "%").replace("\0", "$"))   # systemd: $$ → $, %% → %
# systemd would EXPAND a single `$name` (to the empty string here: no such variable in the unit) — model that too
cmd = [re.sub(r"\$(\w+)", "", c) if "$" in c else c for c in cmd] if MODE == "escape" else cmd
check("…as `/bin/sh -c <script>`", cmd[:2] == ["/bin/sh", "-c"] and len(cmd) == 3, cmd[:2])

TOOLS = T + "/tools"
os.makedirs(TOOLS)
for tool in ("grep", "cat", "sh"):
    p = shutil.which(tool)
    if p:
        os.symlink(p, os.path.join(TOOLS, tool))
FAKE = T + "/fake"
os.makedirs(FAKE)
open(FAKE + "/nft", "w").write(
    '#!/bin/sh\n'
    'echo "$*" >> "$LOG"\n'
    'if [ "$1" = "list" ] && [ "$2" = "table" ]; then case " ${INSTALLED:-} " in *" $4 "*) exit 0;; *) exit 1;; esac; fi\n'
    'exit 0\n')
os.chmod(FAKE + "/nft", 0o755)
OPT = T + "/opt/swg-noded"
os.makedirs(OPT)


def start(build, installed="swg_reach swg_share", nft=True):
    open(OPT + "/swg-noded", "w").write(
        "#!/usr/bin/env python3\n" + ("def _reach_drop_table(res):\n    pass\n" if build == "capable" else "def reconcile(x):\n    pass\n"))
    log = T + "/nft.log"
    open(log, "w").close()
    script = cmd[2].replace("/opt/swg-noded/swg-noded", OPT + "/swg-noded") if len(cmd) == 3 else "exit 9"
    r = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True,
                       env={"PATH": (FAKE + ":" if nft else "") + TOOLS, "INSTALLED": installed, "LOG": log})
    calls = [l.strip() for l in open(log) if l.strip()]
    return r.returncode, [c.split()[-1] for c in calls if c.startswith("delete table inet")], calls


rc, deleted, calls = start("older")
check("⚠️ an older build starting: BOTH tables deleted", sorted(deleted) == ["swg_reach", "swg_share"], calls)
check("…and it exits 0", rc == 0, rc)
rc, deleted, calls = start("capable")
check("⚠️ a capable build starting: nft is never asked to delete anything", deleted == [], calls)
check("…and it exits 0", rc == 0, rc)
rc, deleted, calls = start("older", installed="swg_reach")
check("only the installed table is deleted", deleted == ["swg_reach"], calls)
rc, deleted, calls = start("older", nft=False)
check("no nft on the box: exit 0, nothing attempted", rc == 0 and calls == [], (rc, calls))

print("\n[3] ensure_noded_reach_sweep — the heal")
SD = T + "/systemd"
BIN = T + "/sysbin"
os.makedirs(SD)
os.makedirs(BIN)
open(BIN + "/systemctl", "w").write('#!/bin/sh\necho "$*" >> "$SLOG"\n')
os.chmod(BIN + "/systemctl", 0o755)


def heal(dry=False):
    slog = T + "/systemctl.log"
    open(slog, "w").close()
    subprocess.run(["bash", "-c", 'warn(){ :; }; . "$1" >/dev/null 2>&1; DRYRUN=%s; ensure_noded_reach_sweep /opt/swg-noded "$2"'
                    % ("true" if dry else "false"), "x", LIB, SD],
                   env=dict(os.environ, PATH=BIN + ":" + os.environ.get("PATH", ""), SLOG=slog), capture_output=True, text=True)
    return [l.strip() for l in open(slog) if l.strip()]


DROP = SD + "/swg-noded.service.d/10-swg-reach-sweep.conf"
heal()
check("no swg-noded unit → nothing written (a docker or panel-only box)", not os.path.exists(DROP))
open(SD + "/swg-noded.service", "w").write("[Service]\nExecStart=/opt/swg-noded/swg-noded\n")
heal(dry=True)
check("a dry run writes nothing", not os.path.exists(DROP))
s1 = heal()
check("beside an existing unit: written, and systemd reloaded", os.path.exists(DROP) and "daemon-reload" in s1, s1)
check("…with exactly the rendered content", open(DROP).read() == rendered if os.path.exists(DROP) else False)
s2 = heal()
check("…idempotent: a second pass reloads nothing", s2 == [], s2)
open(DROP, "w").write("[Service]\nExecStartPre=/bin/true\n")
s3 = heal()
check("stale content is rewritten", open(DROP).read() == rendered and "daemon-reload" in s3, s3)

print("\n[4] the capability it asks about is real")
check("`def _reach_drop_table` is defined at the start of a line in swg-noded", re.search(r"^def _reach_drop_table\(", noded, re.M) is not None)

print("\n%s — %d failed" % ("RED" if FAILS else "GREEN", len(FAILS)))
if MODE:
    print("(--perturb%s expects RED above)" % ("" if MODE == "capable" else "-" + MODE))
sys.exit(1 if FAILS else 0)
