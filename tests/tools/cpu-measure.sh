#!/bin/bash
# cpu-measure.sh — what swg-noded and swg-netctl cost on THIS box, measured the way docs/CPU-PLAN.md §1 was. Read-only.
#
#   ssh <box> 'bash -s'                 < tests/tools/cpu-measure.sh     # 60 s, passive: safe on any box, production too
#   ssh <box> 'bash -s -- -w 120'       < tests/tools/cpu-measure.sh     # a longer window
#   ssh <box> 'bash -s -- --exact'      < tests/tools/cpu-measure.sh     # + bpftrace/execsnoop: exact spawns, CPU per
#                                                                        #   command, writes — TEST boxes only (it traces)
#
# The cost that matters is noded's OWN CPU plus its REAPED CHILDREN's (cutime+cstime): the children cost about twice noded's
# own on a 1.8.9 node, and a sampler of utime+stime alone (the 1.8.9 qualification's meas.sh) misses them entirely.
set -u
W=60 EXACT=0
while [ $# -gt 0 ]; do case "$1" in -w) W="$2"; shift 2;; --exact) EXACT=1; shift;; *) shift;; esac; done

echo "== $(hostname) · $(nproc) vCPU · $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ //') · up $(cut -d. -f1 /proc/uptime)s"
echo "   load $(cut -d' ' -f1-3 /proc/loadavg) · cpu pressure: $(head -1 /proc/pressure/cpu 2>/dev/null | cut -d' ' -f2-3)"
for f in /opt/swg-noded/VERSION /opt/swg-panel/VERSION; do [ -r "$f" ] && echo "   $f: $(cat "$f")"; done

# ── swg-noded: own + children, a W-second window and its lifetime; a 5 ms sample of what it spawns ─────────────────────
python3 -I - "$W" "$EXACT" <<'PY'
import collections, os, sys, time
W, EXACT = float(sys.argv[1]), sys.argv[2] == "1"
HZ = os.sysconf("SC_CLK_TCK")
def find():
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
        except OSError:
            continue
        if argv and b"bash" not in argv[0] and any(a.endswith(b"/swg-noded") or a == b"swg-noded" for a in argv):
            return int(p)
def stat(pid):
    s = open("/proc/%d/stat" % pid).read()
    f = s[s.rindex(")") + 2:].split()
    return [int(x) for x in f[11:15]], int(f[19])          # utime stime cutime cstime, starttime
pid = find()
if not pid:
    print("== swg-noded: not running here"); sys.exit(0)
(t0, start) = stat(pid)
age = float(open("/proc/uptime").read().split()[0]) - start / HZ
print("== swg-noded pid %d, up %.1f h — lifetime: own %.2f %%, children %.2f %% of one core" % (
    pid, age / 3600, 100 * (t0[0] + t0[1]) / HZ / age, 100 * (t0[2] + t0[3]) / HZ / age))
seen, pids, n, end = collections.Counter(), set(), 0, time.time() + W
tids = os.listdir("/proc/%d/task" % pid)
while time.time() < end:
    if not EXACT:                                           # the exact mode counts by tracing; don't add a sampler's load
        for t in tids:
            try:
                kids = open("/proc/%d/task/%s/children" % (pid, t)).read().split()
            except OSError:
                continue
            for c in kids:
                try:
                    a = open("/proc/%s/cmdline" % c, "rb").read().split(b"\0")
                except OSError:
                    continue
                k = " ".join(x.decode(errors="replace") for x in a[:4])[:100]
                seen[k] += 1; pids.add((c, k))
        n += 1
        time.sleep(0.005)
    else:
        time.sleep(1)
(t1, _) = stat(pid)
own, kids = (t1[0] + t1[1] - t0[0] - t0[1]) / HZ, (t1[2] + t1[3] - t0[2] - t0[3]) / HZ
print("   window %.0f s: own %.1f %% + children %.1f %% = %.1f %% of one core" % (W, 100 * own / W, 100 * kids / W, 100 * (own + kids) / W))
if not EXACT:
    print("   children sampled (5 ms; short ones undercounted): %d distinct, %.1f/s — by command (distinct · samples):" % (len(pids), len(pids) / W))
    for k, v in collections.Counter(k for _, k in pids).most_common(15):
        print("     %4d  %5d  %s" % (v, seen[k], k))
PY

# ── --exact: every descendant's exec and CPU, by command (bpftrace + execsnoop; test boxes) ──────────────────────────────
if [ "$EXACT" = 1 ]; then
  if ! command -v bpftrace >/dev/null || ! command -v execsnoop-bpfcc >/dev/null; then
    echo "   --exact: bpftrace / execsnoop-bpfcc not installed here — skipped"
  else
    P=$(python3 -I -c 'import os
for p in os.listdir("/proc"):
    if p.isdigit():
        try: a=open("/proc/%s/cmdline"%p,"rb").read().split(b"\0")
        except OSError: continue
        if a and b"bash" not in a[0] and any(x.endswith(b"/swg-noded") or x==b"swg-noded" for x in a): print(p); break')
    T=$(mktemp -d)
    cat > "$T/x.bt" <<BT
tracepoint:sched:sched_process_exit
/ curtask->pid == curtask->tgid && (curtask->real_parent->tgid == $P || curtask->real_parent->real_parent->tgid == $P || curtask->real_parent->real_parent->real_parent->tgid == $P) /
{ printf("X %d %d\n", curtask->tgid, curtask->se.sum_exec_runtime / 1000); }
interval:s:$W { exit(); }
BT
    timeout $((W + 15)) execsnoop-bpfcc > "$T/exec" 2>/dev/null &
    sleep 2; bpftrace "$T/x.bt" > "$T/rt" 2>/dev/null; sleep 1; kill %1 2>/dev/null; wait 2>/dev/null
    python3 -I - "$T" "$W" <<'PY'
import collections, re, sys
T, W = sys.argv[1], float(sys.argv[2])
args = {}
for l in open(T + "/exec"):
    f = l.split(None, 4)
    if len(f) >= 4 and f[1].isdigit():
        args[f[1]] = f[4].strip() if len(f) > 4 else f[0]
def norm(a):
    a = re.sub(r"\b[0-9a-f]{8,}\b", "<h>", a); a = re.sub(r"\b\d+(\.\d+){3}(/\d+)?\b", "<ip>", a)
    a = re.sub(r"(--password|-password)( +|=)\S+", r"\1\2<redacted>", a)
    return re.sub(r"^(/usr)?/s?bin/sh -c ", "sh -c ", a)[:110]
WRITE = re.compile(r"\bnft (add|delete|flush|-f|insert|replace|create|destroy)\b|\bip (route|rule|link|addr) (add|del|replace|flush|change|set)\b|"
                   r"\biptables(-restore)?\b.* -(A|D|I|F|X|N|R|P) |\biptables-restore\b|\bipset (add|del|create|destroy|flush|swap|restore)\b|"
                   r"\bsystemctl (start|stop|restart|enable|disable|reload|daemon-reload)\b|\bswg-agent\b|\bwg(-quick)? (set|up|down)\b|\bsysctl -w\b")
n, us, tot = collections.Counter(), collections.Counter(), 0
writes = collections.Counter()
for l in open(T + "/rt"):
    f = l.split()
    if len(f) == 3 and f[0] == "X":
        k = norm(args.get(f[1], "?")); n[k] += 1; us[k] += int(f[2]); tot += int(f[2])
        if WRITE.search(k):
            writes[k] += 1
print("   --exact %.0f s: %d descendants, %.2f s of their CPU (%.1f %% of one core)" % (W, sum(n.values()), tot / 1e6, 100 * tot / 1e6 / W))
for k, u in us.most_common(25):
    print("     %7.0f ms  %4d ×  %5.1f ms each  %s" % (u / 1000, n[k], u / 1000 / n[k], k))
print("   writes in the window (a steady node should show none): %d" % sum(writes.values()))
for k, v in writes.most_common(15):
    print("     %4d ×  %s" % (v, k))
PY
    rm -rf "$T"
  fi
fi

# ── swg-netctl: what its last starts cost, and whether the idle gate skipped them ────────────────────────────────────────
if [ -f /etc/systemd/system/swg-netctl.service ]; then
  echo "== swg-netctl (timer $(systemctl show swg-netctl.timer -p ActiveState --value), path $(systemctl show swg-netctl.path -p ActiveState --value)," \
       "gate: $([ -f /etc/systemd/system/swg-netctl.service.d/swg-due.conf ] && echo yes || echo no))"
  for i in 1 2 3 4 5 6; do
    a=$(systemctl show swg-netctl.service -p InactiveExitTimestampMonotonic --value)
    for _ in $(seq 1 30); do [ "$(systemctl show swg-netctl.service -p InactiveExitTimestampMonotonic --value)" != "$a" ] && break; sleep 0.5; done
    sleep 2
    printf '   start: result=%-15s cpu=%s ms\n' "$(systemctl show swg-netctl.service -p Result --value)" \
      "$(( $(systemctl show swg-netctl.service -p CPUUsageNSec --value 2>/dev/null || echo 0) / 1000000 ))"
  done
  if read -r due at < /run/swg-netctl.due 2>/dev/null; then        # `<due> <the run's time>` (5d07661f)
    echo "   stamp: next own work in $(( ${due:-0} - $(date +%s) )) s, written $(( $(date +%s) - ${at:-0} )) s ago"
  fi
fi
