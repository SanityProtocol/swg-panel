#!/usr/bin/env python3
"""Self-test — on systemd < 254 the turn / WDTT / csqtt units get a restart back-off that systemd understands (1.8.9
qualification D12-1).

Our units back off with `RestartSec=3 RestartSteps=8 RestartMaxDelaySec=300`; the last two came in systemd 254, so Debian 12
(252) and Ubuntu 22.04 (249) ignore them and restart a failing server every 3 s for ever. swg-noded writes, at its start and
only on systemd < 254, a PREFIX drop-in per family (`vk-turn-proxy-.service.d/`, `swg-wdtt-.service.d/`, `swg-csqtt-.service.d/`)
carrying `RestartSec=30` — every unit of the family, existing ones included, takes it at its next restart; nothing is restarted
for it. (Measured on systemd 255: such a drop-in reaches an existing vk-turn-proxy-<x>.service and its RestartSec overrides the
unit's own — RestartUSec 3s → 30s.)

  [1] systemd 252 / 249: the three drop-ins, `[Service] RestartSec=30`, then ONE daemon-reload; a second start writes nothing
      and reloads nothing; a stale one is rewritten
  [2] systemd 254 / 255, an unreadable version, a docker node: nothing written, nothing reloaded
  [3] main() asks it at start, beside the log-namespace drop-ins

Run: python3 tests/restart_backoff_selftest.py      (0 = pass)
     --perturb   the drop-ins are never written (the shipped code) → RED on [1]
"""
import os, re, shutil, subprocess, sys, tempfile, types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
NODED = os.environ.get("SWG_NODED") or os.path.join(ROOT, "swg-noded")
PERTURB = "--perturb" in sys.argv[1:]
FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

src = open(NODED, encoding="utf-8").read()
ANCHOR = '    if not m or int(m.group(1)) >= 254:\n        return\n'
if PERTURB:
    assert src.count(ANCHOR) == 1, "perturbation anchor missing — would FALSE-PASS"
    src = src.replace(ANCHOR, "    return\n")
N = types.ModuleType("n"); N.__dict__.update({"__name__": "n", "__file__": NODED})
exec(compile(src.split("\nif __name__ ==")[0], "swg-noded", "exec"), N.__dict__)
T = tempfile.mkdtemp(prefix="restartbo-")
N.UNIT_DIR_PERSIST = os.path.join(T, "etc"); N.UNIT_DIR_RUNTIME = os.path.join(T, "run"); N.unit_dir_persists = lambda: True
CALLS, VER = [], ["systemd 252 (252.33-1~deb12u1)\n+PAM +AUDIT +SELINUX\n"]
def run(cmd, **k):
    CALLS.append(" ".join(cmd))
    return subprocess.CompletedProcess(cmd, 0, VER[0] if cmd[:2] == ["systemctl", "--version"] else "", "")
N.run = run
FAM = ("vk-turn-proxy-.service", "swg-wdtt-.service", "swg-csqtt-.service")
drop = lambda u: os.path.join(N.UNIT_DIR_PERSIST, u + ".d", "swg-restart.conf")
reloads = lambda: sum(1 for c in CALLS if c == "systemctl daemon-reload")

print("[1] systemd < 254")
N.NODE_KIND = "baremetal"
N._restart_dropins()
check("systemd 252 (Debian 12): every family gets `[Service] RestartSec=30`, then one daemon-reload",
      all(os.path.exists(drop(u)) and open(drop(u)).read() == "[Service]\nRestartSec=30\n" for u in FAM) and reloads() == 1,
      (CALLS, [os.path.exists(drop(u)) for u in FAM]))
CALLS.clear(); N._restart_dropins()
check("…a second start writes nothing and reloads nothing", reloads() == 0, CALLS)
os.makedirs(os.path.dirname(drop(FAM[1])), exist_ok=True); open(drop(FAM[1]), "w").write("[Service]\nRestartSec=3\n")
CALLS.clear(); VER[0] = "systemd 249 (249.11-0ubuntu3.12)\n"; N._restart_dropins()
check("…systemd 249 (Ubuntu 22.04): a stale one is rewritten, one reload", open(drop(FAM[1])).read() == "[Service]\nRestartSec=30\n"
      and reloads() == 1, CALLS)

print("\n[2] nothing elsewhere")
for label, ver, kind in (("systemd 254", "systemd 254 (254.5-1)\n", "baremetal"), ("systemd 255", "systemd 255 (255.4-1ubuntu8)\n", "baremetal"),
                         ("an unreadable version", "", "baremetal"), ("a docker node", "systemd 249\n", "docker")):
    shutil.rmtree(N.UNIT_DIR_PERSIST, ignore_errors=True); CALLS.clear(); VER[0] = ver; N.NODE_KIND = kind
    N._restart_dropins()
    check("%s: nothing written, nothing reloaded" % label, not os.path.exists(N.UNIT_DIR_PERSIST) and reloads() == 0, CALLS)

print("\n[3] main() asks it at start")
mm = re.search(r"^def main\(\):.*?(?=^def |\Z)", src, re.S | re.M)
check("…beside the log-namespace drop-ins, before the first pass", bool(mm) and "_restart_dropins()" in mm.group(0)
      and mm.group(0).index("_log_ns_dropins()") < mm.group(0).index("_restart_dropins()"))
shutil.rmtree(T, ignore_errors=True)

print("")
if PERTURB:
    print("PERTURB OK — %d checks went red" % len(FAILS) if FAILS else "PERTURB FAILED — nothing went red")
    sys.exit(0 if FAILS else 1)
print("ALL PASS" if not FAILS else "FAILED: %d — %s" % (len(FAILS), FAILS))
sys.exit(1 if FAILS else 0)
