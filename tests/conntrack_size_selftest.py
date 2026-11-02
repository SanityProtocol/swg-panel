#!/usr/bin/env python3
"""Self-test — conntrack's table is sized from RAM and reported (docs/SCALE-PLAN.md N2).

A full conntrack table refuses NEW connections for every user on the node at once. The kernel sizes it small (8,192 on
msk-main's 1 GB), and a faster datapath (DATAPATH DP1/DP2) reaches it sooner.

  [1] swg-noded conntrack_size, against a stand-in /proc: 65,536 entries a GB of RAM (rounded up), buckets a quarter,
      buckets first; a table already as large is left alone, a higher operator value is never lowered (max or buckets);
      a raise that does not take is said once and tried again an hour later, not every pass; a container writes nothing
      (its /proc/sys is read-only, the table is the host's); no conntrack loaded → nothing, and the next pass tries
  [2] collect_health reports `ct: [count, max]`, and nothing when they cannot be read
  [3] lib/common.sh conntrack_size_host (a Docker node's host), run as written under set -euo pipefail against a
      stand-in /proc and /etc: the same size, the drop-in AND modules-load.d (without nf_conntrack loaded at boot
      systemd-sysctl drops net.netfilter.* silently), raised live; a second run changes nothing; a higher operator value
      is never lowered, in the drop-in either; no conntrack → no drop-in, no claim
  [4] the call sites: noded's every pass, install-docker.sh, update.sh's Docker node profiles; uninstall.sh removes both
  [5] the node page: `connection table N%` from 80 % (warn), hot from 95 %, nothing below or for a malformed `ct`

Run: python3 tests/conntrack_size_selftest.py   (0 = pass)
  --plant <x>  one defect, RED expected (exit 0 when caught):
     everypass   a raise that did not take is tried on every pass                       [1]
     docker      a container writes its read-only /proc/sys                             [1]
     lower       the host helper writes the RAM size over a larger operator value        [3]
     nomodload   the host helper writes no modules-load.d                               [3]
     alert90     the node page warns only from 90 %                                     [5]
"""
import atexit, importlib.machinery, importlib.util, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PLANT = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else ""
PLANTS = {
    "everypass": ("[1]", 'if cur >= want or (tried and time.monotonic() - tried[1] < 3600):', "if cur >= want:"),
    "docker": ("[1]", '    if NODE_KIND == "docker":\n        return\n    p = os.path.join(proc_root, "sys/net/netfilter/nf_conntrack_")',
               '    p = os.path.join(proc_root, "sys/net/netfilter/nf_conntrack_")'),
    "lower": ("[3]", '  [ "$cur" -gt "$want" ] && want="$cur"                   # never lower', '  :                   # never lower'),
    "nomodload": ("[3]", '  [ "$(cat "$m" 2>/dev/null)" = nf_conntrack ] || { mkdir -p /etc/modules-load.d && echo nf_conntrack > "$m"; } 2>/dev/null || true\n', ""),
    "alert90": ("[5]", "ct[1] > 0 && ct[0] / ct[1] >= 0.8)", "ct[1] > 0 && ct[0] / ct[1] >= 0.9)"),
}
FAILS, SECTION = [], [""]


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:400]) if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(SECTION[0] + " " + name)


TMP = tempfile.mkdtemp(prefix="ct-size-")
atexit.register(shutil.rmtree, TMP, True)
SRC = {"swg-noded": open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read(),
       "lib/common.sh": open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read(),
       "js/screen-nodes.js": open(os.path.join(ROOT, "js", "screen-nodes.js"), encoding="utf-8").read()}
if PLANT:
    if PLANT not in PLANTS:
        sys.exit("unknown plant %r" % PLANT)
    _, a, b = PLANTS[PLANT]
    f = next((k for k, v in SRC.items() if v.count(a) == 1), None)
    if not f:
        sys.exit("plant anchor for %s not found once — this run would measure nothing" % PLANT)
    SRC[f] = SRC[f].replace(a, b)
nodedp = os.path.join(TMP, "noded.py")
open(nodedp, "w", encoding="utf-8").write(SRC["swg-noded"])
os.environ["SWG_NODED_STATE"] = TMP
_l = importlib.machinery.SourceFileLoader("swgnoded_ct", nodedp)
N = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_ct", _l))
try:
    _l.exec_module(N)
except SystemExit:
    pass
SAID = []
N.log = lambda lvl, fmt, *a: SAID.append(fmt % a)
NOW = [5000.0]
N.time = type("T", (), {"time": staticmethod(lambda: NOW[0]), "monotonic": staticmethod(lambda: NOW[0])})
P = os.path.join(TMP, "proc")
NF = os.path.join(P, "sys/net/netfilter")


def proc(mem_kb=984548, mx=8192, bk=8192, count=660, loaded=True):
    shutil.rmtree(P, True)
    os.makedirs(NF)
    open(os.path.join(P, "meminfo"), "w").write("MemTotal:       %d kB\nMemFree:          1000 kB\n" % mem_kb)
    if loaded:
        for k, v in (("max", mx), ("buckets", bk), ("count", count)):
            open(os.path.join(NF, "nf_conntrack_" + k), "w").write("%d\n" % v)
    N._CT.update(want=None, tried=None)
    SAID.clear()


rd = lambda k: int(open(os.path.join(NF, "nf_conntrack_" + k)).read())

# ── [1] noded ───────────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[1]"
print("\n[1] swg-noded raises the table, never lowers it")
N.NODE_KIND = "baremetal"
proc()
N.conntrack_size(P)
check("1 GB (984,548 kB): 8,192 → 65,536 entries, buckets 8,192 → 16,384, said once", (rd("max"), rd("buckets")) == (65536, 16384)
      and len(SAID) == 1 and "8192 -> 65536" in SAID[0], ((rd("max"), rd("buckets")), SAID))
SAID.clear(); N.conntrack_size(P)
check("…the next pass reads it and does nothing", (rd("max"), rd("buckets")) == (65536, 16384) and not SAID, SAID)
proc(mem_kb=3 * 1048576 + 1)
N.conntrack_size(P)
check("just over 3 GB: rounded up to 4 GB → 262,144", rd("max") == 262144 and rd("buckets") == 65536, (rd("max"), rd("buckets")))
proc(mx=500000, bk=8192)
N.conntrack_size(P)
check("an operator's 500,000: left alone, buckets too", (rd("max"), rd("buckets")) == (500000, 8192) and not SAID, (rd("max"), SAID))
proc(mx=8192, bk=100000)
N.conntrack_size(P)
check("an operator's larger buckets are never lowered when the max is raised", (rd("max"), rd("buckets")) == (65536, 100000),
      (rd("max"), rd("buckets")))
if os.geteuid() != 0:                                          # root writes a 0444 file anyway: this half needs a user
    proc()
    os.chmod(os.path.join(NF, "nf_conntrack_max"), 0o444)
    N.conntrack_size(P)
    for _ in range(10):
        NOW[0] += 5
        N.conntrack_size(P)
    check("a raise that does not take: said once, not tried again within the hour", rd("max") == 8192
          and len([s for s in SAID if "could not be raised" in s]) == 1 and N._CT["tried"], SAID)
    os.chmod(os.path.join(NF, "nf_conntrack_max"), 0o644)
    NOW[0] += 5
    N.conntrack_size(P)
    check("…still not within the hour, writable or not", rd("max") == 8192, rd("max"))
    NOW[0] += 3600
    N.conntrack_size(P)
    check("…an hour later it is tried again, and takes", rd("max") == 65536 and N._CT["tried"] is None, (rd("max"), N._CT))
proc(loaded=False)
N.conntrack_size(P)
check("conntrack not loaded: nothing written, nothing said", not os.path.exists(os.path.join(NF, "nf_conntrack_max")) and not SAID, SAID)
proc()
N.NODE_KIND = "docker"
N.conntrack_size(P)
check("a container writes nothing (its /proc/sys is read-only; the host's helper sizes it)", rd("max") == 8192 and not SAID, (rd("max"), SAID))
N.NODE_KIND = "baremetal"

# ── [2] the report ──────────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[2]"
print("\n[2] the node reports count / max")
proc(count=7000)
h = N.collect_health(proc_root=P, mounts=[])
check("collect_health: ct = [count, max]", h.get("ct") == [7000, 8192], h.get("ct"))
proc(loaded=False)
check("…and no `ct` where conntrack cannot be read", "ct" not in N.collect_health(proc_root=P, mounts=[]))

# ── [3] the Docker host's helper ────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[3]"
print("\n[3] lib/common.sh conntrack_size_host")
m = re.search(r"^conntrack_size_host\(\)\{.*?^\}\n", SRC["lib/common.sh"], re.S | re.M)
check("the helper is in lib/common.sh", bool(m))
fn = (m.group(0) if m else "").replace("/proc/", P + "/").replace("/etc/", os.path.join(TMP, "etc") + "/")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN, exist_ok=True)
open(os.path.join(BIN, "sysctl"), "w").write('#!/bin/sh\nkv="$3"; k="${kv%%%%=*}"; k="${k#net.netfilter.}"\nprintf "%%s\\n" "${kv#*=}" > "%s/$k"\n' % NF)
open(os.path.join(BIN, "modprobe"), "w").write("#!/bin/sh\nexit 0\n")
for b in ("sysctl", "modprobe"):
    os.chmod(os.path.join(BIN, b), 0o755)
DROP, MOD = os.path.join(TMP, "etc/sysctl.d/99-swg-conntrack.conf"), os.path.join(TMP, "etc/modules-load.d/swg-conntrack.conf")


def host(**kw):
    shutil.rmtree(os.path.join(TMP, "etc"), True)
    proc(**kw)
    return again()


def again():
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n" + fn + '\nif false; then :; else conntrack_size_host; fi\necho "CHANGED=$CT_SIZE_CHANGED"'],
                       capture_output=True, text=True, env=dict(os.environ, PATH=BIN + ":" + os.environ["PATH"]))
    return r.returncode, r.stdout.strip(), r.stderr.strip()


drop = lambda: open(DROP).read() if os.path.exists(DROP) else ""
r = host(mem_kb=2000000)
check("2 GB: raised live to 131,072 / 32,768, said", r[0] == 0 and r[1].endswith("CHANGED=1") and (rd("max"), rd("buckets")) == (131072, 32768), r)
check("…the drop-in holds the size", "net.netfilter.nf_conntrack_max = 131072" in drop()
      and "net.netfilter.nf_conntrack_buckets = 32768" in drop(), drop())
check("…and nf_conntrack is loaded at boot, or systemd-sysctl drops the keys", os.path.exists(MOD) and open(MOD).read().strip() == "nf_conntrack",
      os.path.exists(MOD))
r = again()
check("a second run changes nothing and claims nothing", r[0] == 0 and r[1].endswith("CHANGED=0"), r)
r = host(mx=500000, bk=200000)
check("an operator's larger values are never lowered, in the drop-in either", r[1].endswith("CHANGED=0") and (rd("max"), rd("buckets")) == (500000, 200000)
      and "nf_conntrack_max = 500000" in drop() and "nf_conntrack_buckets = 200000" in drop(), (r, drop()))
r = host(loaded=False)
check("no conntrack on the host: no drop-in, no claim, no failure", r[0] == 0 and r[1].endswith("CHANGED=0") and not drop(), r)

# ── [4] the call sites ──────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[4]"
print("\n[4] who calls it")
_main = SRC["swg-noded"][SRC["swg-noded"].index("\ndef main("):]
_loop = _main[_main.index("    while True:"):]
check("noded: every pass, before the snapshot", -1 < _loop.find("conntrack_size()") < _loop.find("build_snapshot("))
idk = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
upd = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
uni = open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8").read()
check("install-docker.sh sizes the host (beside the socket-buffer caps, the node step)", "else conntrack_size_host" in idk
      and idk.index("else conntrack_size_host") - idk.index("else turn_sock_buf_host") in range(1, 800))
_up = upd[upd.index("      turn_sock_buf_host"):]
check("update.sh sizes it for the Docker node profiles", "conntrack_size_host" in _up[:800])
check("uninstall.sh removes the drop-in and the modules-load file",
      "/etc/sysctl.d/99-swg-conntrack.conf" in uni and "/etc/modules-load.d/swg-conntrack.conf" in uni)

# ── [5] the node page ───────────────────────────────────────────────────────────────────────────────────────────────────
SECTION[0] = "[5]"
print("\n[5] the node page warns")
js = SRC["js/screen-nodes.js"]
blk = js[js.index("  const ct = health && health.ct;"):]
blk = blk[:blk.index("  }\n") + 4]
harness = ("const T = (s, a) => s.replace('{v1}', a.v1);\nfunction f(health) { const out = [];\n" + blk + "return out; }\n"
           "const cases = __CASES__;\nconsole.log(JSON.stringify(cases.map(c => f({ ct: c }))));\n")
CASES = [[6500, 8192], [6600, 8192], [7800, 8192], [100, 0], "x", [None, 8192], [8192, 8192]]
try:
    out = json.loads(subprocess.run(["node", "-e", harness.replace("__CASES__", json.dumps(CASES))], capture_output=True, text=True, timeout=30).stdout)
except Exception as e:
    out = [str(e)] * len(CASES)
check("79 %: nothing", out[0] == [], out[0])
check("81 %: warn, `connection table 81%`", out[1] == [{"sev": "warn", "msg": "connection table 81%"}], out[1])
check("95 %: hot", out[2] == [{"sev": "hot", "msg": "connection table 95%"}], out[2])
check("a max of 0, a string, a null count: nothing, no throw", out[3] == out[4] == out[5] == [], out[3:6])
check("full: hot, 100 %", out[6] == [{"sev": "hot", "msg": "connection table 100%"}], out[6])
check("the Russian string exists", '"connection table {v1}%":' in open(os.path.join(ROOT, "js/lang/ru.js"), encoding="utf-8").read())

print()
if PLANT:
    sec = PLANTS[PLANT][0]
    red = [f for f in FAILS if f.split()[0] == sec]
    print("plant %s: %s" % (PLANT, ("RED as it must be (%d in %s)" % (len(red), sec)) if red else "NOT CAUGHT"))
    sys.exit(0 if red else 1)
print("FAIL: %d" % len(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
