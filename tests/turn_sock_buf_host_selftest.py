#!/usr/bin/env python3
"""Self-test: a Docker node's socket-buffer caps are raised and persisted on the HOST (svo-im, 2026-10-14).

swg-noded raises net.core.{r,w}mem_max for the turn-family listeners (csqtt asks for 16 MiB) and persists them in
/etc/sysctl.d/99-swg-turn.conf. From a container it can do neither — /proc/sys is read-only there and the caps are the
host's — so it warned on every start, and its "wrote … survives a reboot" line wrote the container's own /etc.

  [1] lib/common.sh turn_sock_buf_host, run as written against a stand-in /proc/sys and /etc/sysctl.d (sysctl stubbed):
      sized as swg-noded's _turn_sock_target for up to four listeners — udp_mem's ceiling / 8, capped at 24 MiB, floor
      4 MiB, the floor when udp_mem cannot be read; both keys written and applied; a second run writes nothing
  [2] only raises: a higher cap the operator set is kept, the other key still raised
  [3] the call sites: install-docker.sh's node/master networking step and update.sh's node-bearing Docker profiles
  [4] swg-noded in a container names the host fix (the update, or sysctl -w on the host) and never persists into its
      own /etc; a bare-metal node still persists

Run: python3 tests/turn_sock_buf_host_selftest.py   (0 = pass)
     --perturb          the helper ignores the cap already set (lowers an operator's value) → RED in [2]
     --perturb-persist  swg-noded persists inside a container again → RED in [4]
"""
import atexit, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = "--perturb" in sys.argv
PERTURB_PERSIST = "--perturb-persist" in sys.argv

FAILS = []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + json.dumps(detail, default=str)[:400]) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def plant(src, a, b, what):
    if src.count(a) != 1:
        print("PLANT ANCHOR MISSING — %s (%d)" % (what, src.count(a))); sys.exit(1)
    print("(perturbed: %s — this run must FAIL)" % what)
    return src.replace(a, b)

TMP = tempfile.mkdtemp(prefix="sockbuf-")
atexit.register(shutil.rmtree, TMP, True)
common = open(os.path.join(ROOT, "lib", "common.sh"), encoding="utf-8").read()
m = re.search(r"^turn_sock_buf_host\(\)\{.*?^\}\n", common, re.S | re.M)
fn = m.group(0) if m else ""
if PERTURB:
    fn = plant(fn, '    v=$want; [ "$cur" -gt "$v" ] && v=$cur\n', "    v=$want\n", "the cap already set ignored")
PROC, ETC, BIN = os.path.join(TMP, "proc"), os.path.join(TMP, "etc"), os.path.join(TMP, "bin")
fn = fn.replace("/proc/sys/", PROC + "/").replace("/etc/sysctl.d", ETC)
os.makedirs(BIN)
open(os.path.join(BIN, "sysctl"), "w").write('#!/bin/sh\necho "$*" >> "%s/sysctl.calls"\n' % TMP)
os.chmod(os.path.join(BIN, "sysctl"), 0o755)

def run(udp_mem, rmem=212992, wmem=212992, fresh=True):
    if fresh:
        shutil.rmtree(PROC, True); shutil.rmtree(ETC, True)
        with __import__("contextlib").suppress(FileNotFoundError):
            os.remove(os.path.join(TMP, "sysctl.calls"))
    os.makedirs(PROC + "/net/ipv4", exist_ok=True); os.makedirs(PROC + "/net/core", exist_ok=True)
    if udp_mem is not None:
        open(PROC + "/net/ipv4/udp_mem", "w").write(udp_mem + "\n")
    open(PROC + "/net/core/rmem_max", "w").write("%d\n" % rmem)
    open(PROC + "/net/core/wmem_max", "w").write("%d\n" % wmem)
    out = subprocess.run(["bash", "-c", fn + '\nturn_sock_buf_host; echo "changed=$TURN_SOCK_BUF_CHANGED"'],
                         capture_output=True, text=True, env=dict(os.environ, PATH=BIN + ":" + os.environ["PATH"]))
    conf = ETC + "/99-swg-turn.conf"
    body = open(conf).read() if os.path.exists(conf) else ""
    vals = dict(re.findall(r"^net\.core\.(\w+) = (\d+)$", body, re.M))
    calls = open(os.path.join(TMP, "sysctl.calls")).read() if os.path.exists(os.path.join(TMP, "sysctl.calls")) else ""
    return out.stdout.strip(), {k: int(v) for k, v in vals.items()}, calls

print("[1] the helper, as written")
check("[1] the function is in lib/common.sh", bool(fn), "")
o, v, calls = run("44562 59418 89124")                # svo-im: 2 GB RAM
check("[1] svo-im's udp_mem (89124 pages) → both caps 24 MiB, written and applied",
      v == {"rmem_max": 25165824, "wmem_max": 25165824} and o == "changed=1" and "-p" in calls, (o, v, calls))
o2, v2, calls2 = run("44562 59418 89124", 25165824, 25165824, fresh=False)
check("[1] a second run writes nothing (changed=0, no sysctl)", o2 == "changed=0" and calls2 == calls, (o2, calls2))
o, v, _ = run("10000 15000 20000")
check("[1] a small box: udp_mem's ceiling / 8 (20000 pages → 10240000)", v == {"rmem_max": 10240000, "wmem_max": 10240000}, v)
o, v, _ = run("2000 3000 4000")
check("[1] a tiny box: the 4 MiB floor", v == {"rmem_max": 4194304, "wmem_max": 4194304}, v)
o, v, _ = run(None)
check("[1] udp_mem unreadable: the floor, not the maximum", v == {"rmem_max": 4194304, "wmem_max": 4194304}, v)

print("\n[2] only raises")
o, v, _ = run("44562 59418 89124", rmem=33554432)
check("[2] an operator's 32 MiB rmem_max is kept; wmem_max still raised to 24 MiB",
      v == {"rmem_max": 33554432, "wmem_max": 25165824}, v)

print("\n[3] the call sites")
inst = open(os.path.join(ROOT, "install-docker.sh"), encoding="utf-8").read()
upd = open(os.path.join(ROOT, "update.sh"), encoding="utf-8").read()
blk = inst[inst.find('if [ "$PROFILE" = node ] || [ "$PROFILE" = master ]; then'):inst.find("# ── turn-proxy management")]
check("[3] install-docker.sh: the node/master networking step raises them (host and bridge alike)",
      "else turn_sock_buf_host;" in blk and blk.count("turn_sock_buf_host") == 1, "")
case = upd[upd.find('  case "$prof" in node|master|host-node)'):upd.find("  # migrate existing docker panels")]
check("[3] update.sh: every node-bearing Docker profile, so svo-im-like nodes are healed by an update",
      "      turn_sock_buf_host" in case, "")

print("\n[4] swg-noded in a container")
nd = open(os.path.join(ROOT, "swg-noded"), encoding="utf-8").read()
if PERTURB_PERSIST:
    nd = plant(nd, '    if NODE_KIND != "docker":                          # a container\'s /etc/sysctl.d is its own',
               '    if True:                          # a container\'s /etc/sysctl.d is its own', "a container persists again")
fb = nd[nd.find("def _turn_sock_bufs("):nd.find("def _turn_sock_persist(")]
check("[4] the container warning names the host fix", 'elif NODE_KIND == "docker":' in fb and "a container cannot raise it" in fb
      and "or sysctl -w net.core.%s=%d on the host" in fb, "")
check("[4] …and a container never persists into its own /etc; bare metal still does",
      re.search(r'\n    if NODE_KIND != "docker":[^\n]*\n        _turn_sock_persist\(want\)\n', fb) is not None, "")

if FAILS:
    print("\n%d FAIL" % len(FAILS))
    if PERTURB or PERTURB_PERSIST:
        print("PERTURB OK — %d check(s) went red" % len(FAILS)); sys.exit(0)
    sys.exit(1)
print("\nALL PASS")
if PERTURB or PERTURB_PERSIST:
    print("PERTURB NOT CAUGHT — nothing went red"); sys.exit(1)
