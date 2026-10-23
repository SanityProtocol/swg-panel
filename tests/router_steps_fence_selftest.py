#!/usr/bin/env python3
"""Self-test: the "Other router" steps of a dial-in exit's router config (js/screen-settings.js routerSteps, LX_MASQ) let
the node's traffic out to the internet only — masqueraded as the router — and never into the router's local networks or
to the router itself (1.8.11 S9d; s9d-router-steps verify F8, s9d-f8-lan F1–F5).

The node sends EVERYTHING but its own subnets into an exit (an exit's table is `default dev <exit>`), so a VPN user's
packet to 192.168.1.10 reaches the router; what the router lets through is the operator's LAN. Two earlier versions of
these steps looked fenced and were not: `-i <tun> -o eth0 -j ACCEPT` let a one-NIC box's LAN through (it sits behind
eth0 itself), and a private-range DROP before a bare ACCEPT let a tailnet (100.64/10) through; both left the box's own
services (INPUT) open. Only running the commands answers this, so [2] does.

  [1] hermetic: the commands are read from the SPA source as the router config builds them — only `${tag}` and `${addr}`
      interpolated, the uplink named once (`UPLINK=eth0`)
  [2] on the real kernel, in throwaway network namespaces, with the router's FORWARD policy DROP and again ACCEPT: the
      commands run as shown (each must succeed); from the node behind the tunnel, two internet hosts answer (TCP too, and
      it arrives from the router's address), while the LAN behind the uplink, a LAN on a second NIC, a tailnet, a
      public-range network on another interface, and the router's own tunnel and LAN addresses do not

[2] runs as root or through `sudo -n` (ip netns + iptables); without either it is SKIPPED, and says so — never passed.
The namespaces are named by this process's pid and deleted on the way out; the host's own ruleset is never touched and
nothing leaves the namespaces (the "internet" is TEST-NET addresses on a veth).
Run: python3 tests/router_steps_fence_selftest.py
     --perturb   five plants, each on its own: the private-range drop, the chain's final drop, the uplink on the chain's
                 accept, the FORWARD jump to the chain, the INPUT drop — each must turn [2] red. Prints "PERTURB OK",
                 exit 0 (exit 1 if a plant stayed green); SKIPPED plants are named as such.
"""
import contextlib, signal, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SPA = os.path.join(ROOT, "js", "screen-settings.js")
TAG, ADDR = "swg-b814d3e7", "10.254.0.0"

FAILS, SKIPS = [], []
def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (("  — " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAILS.append(name)

def commands(src):
    """The Linux block as the router config shows it, for the tunnel TAG and the node address ADDR."""
    i = src.find("LX_MASQ = `")
    if i < 0:
        return None, ["LX_MASQ not found"]
    blk = src[i:src.index("`;", i) + 2]
    raw = "".join(re.findall(r"`([^`]*)`", blk))
    unknown = sorted(set(re.findall(r"\$\{([^}]*)\}", raw)) - {"tag", "addr"})
    return raw.replace("${tag}", TAG).replace("${addr}", ADDR).replace("\\n", "\n"), unknown

def run_rig(cmd, timeout):
    """→ (stdout, stderr). On a timeout the whole session gets TERM — `sudo` passes it on, and the rig's trap deletes its
    namespaces; killing only the child left them behind (s9d-f8-lan F10)."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        return p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGTERM)
        try:
            return p.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            return p.communicate()

def sudo():
    if os.geteuid() == 0:
        return []
    if shutil.which("sudo") and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        return ["sudo", "-n"]
    return None

RIG = r'''
set -u
P=s9f$$PID
NS="r n i l t"
cleanup() { for n in $NS; do ip netns del $P-$n 2>/dev/null; done; }
trap cleanup EXIT
trap 'exit 1' INT TERM     # …and on a timeout's TERM too: the EXIT trap then deletes the namespaces
cleanup
for n in $NS; do ip netns add $P-$n; ip -n $P-$n link set lo up; done
pair() { ip link add "$2" netns $P-$1 type veth peer name "$4" netns $P-$3 && ip -n $P-$1 link set "$2" up && ip -n $P-$3 link set "$4" up; }
pair r $TAG n tun0; pair r eth0 i up0; pair r lan0 l lan0; pair r ts0 t ts0
ip -n $P-r addr add 10.254.0.1/31 dev $TAG; ip -n $P-n addr add $ADDR/31 dev tun0; ip -n $P-n route add default via 10.254.0.1
ip -n $P-r addr add 198.51.100.2/24 dev eth0; ip -n $P-r addr add 192.168.1.5/24 dev eth0      # one NIC: the LAN is behind eth0 too
ip -n $P-i addr add 198.51.100.1/24 dev up0; ip -n $P-i addr add 192.168.1.10/24 dev up0; ip -n $P-i addr add 203.0.113.9/32 dev lo
ip -n $P-r route add default via 198.51.100.1
ip -n $P-r addr add 192.168.50.1/24 dev lan0; ip -n $P-l addr add 192.168.50.10/24 dev lan0; ip -n $P-l route add default via 192.168.50.1
ip -n $P-r addr add 100.64.0.1/10 dev ts0; ip -n $P-t addr add 100.101.102.103/10 dev ts0; ip -n $P-t route add default via 100.64.0.1
ip -n $P-r addr add 192.0.2.1/24 dev ts0; ip -n $P-t addr add 192.0.2.10/24 dev ts0     # a public-range network that is not the uplink
ip netns exec $P-r iptables -P FORWARD $POLICY
if ! ip netns exec $P-r bash -e -c "$CMDS" >/dev/null 2>&1; then echo "cmds: FAILED"; exit 0; fi
echo "cmds: ok"
# pasted again (s9d-f8-lan F7): it must succeed and leave exactly the rules the first paste made
N1=$(ip netns exec $P-r iptables-save | grep -c -- "$TAG")
ip netns exec $P-r bash -e -c "$CMDS" >/dev/null 2>&1 && echo "again: ok" || echo "again: FAILED"
N2=$(ip netns exec $P-r iptables-save | grep -c -- "$TAG")
[ "$N1" = "$N2" ] && echo "rules: same" || echo "rules: $N1 -> $N2"
for d in 203.0.113.9 198.51.100.1 192.168.1.10 192.168.50.10 100.101.102.103 192.0.2.10 10.254.0.1 192.168.1.5; do
  ip netns exec $P-n ping -c1 -W1 -q $d >/dev/null 2>&1 && echo "$d: reached" || echo "$d: blocked"; done
ip netns exec $P-i timeout 4 python3 -c "
import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(('203.0.113.9',8443)); s.listen(1); s.settimeout(3)
c,a=s.accept(); print('tcp: from', a[0])" &
L=$!; sleep 0.5
ip netns exec $P-n timeout 3 python3 -c "import socket; socket.create_connection(('203.0.113.9',8443),2).close()" >/dev/null 2>&1 || echo "tcp: refused"
wait $L 2>/dev/null
'''

WANT = {"203.0.113.9": "reached", "198.51.100.1": "reached", "192.168.1.10": "blocked", "192.168.50.10": "blocked",
        "100.101.102.103": "blocked", "192.0.2.10": "blocked", "10.254.0.1": "blocked", "192.168.1.5": "blocked"}
SEEN = {"192.168.1.10": "the LAN behind the uplink (a one-NIC box)", "192.168.50.10": "a LAN on a second NIC",
        "100.101.102.103": "a tailnet (100.64/10)",
        "192.0.2.10": "a public-range network on another interface (a second tunnel, a provider's network)", "10.254.0.1": "the router's tunnel address (INPUT)",
        "192.168.1.5": "the router's LAN address (INPUT)", "203.0.113.9": "an internet host past the uplink's gateway",
        "198.51.100.1": "the uplink's gateway"}

def run_checks(src):
    cmds, unknown = commands(src)
    check("[1] the Linux steps are read from the SPA as built — only ${tag}/${addr} interpolated", cmds is not None and not unknown, unknown)
    check("[1] …the uplink is named once (UPLINK=eth0) and used by name", bool(cmds) and cmds.count("eth0") == 1
          and cmds.startswith("UPLINK=eth0\n") and "$UPLINK" in cmds, cmds)
    _vars = sorted(set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", cmds or "")))
    check("[1] …no rule is held in a variable: UPLINK is the only one, a single word in any shell (zsh does not split $R)",
          _vars == ["UPLINK"], _vars)
    sd = sudo()
    if sd is None or not shutil.which("ip") or not shutil.which("iptables") and not os.path.exists("/usr/sbin/iptables"):
        SKIPS.append("[2]"); print("  SKIPPED [2] — no root / `sudo -n`, ip or iptables here; [1] still ran"); return
    # both iptables backends: the nft one, and the legacy one through a PATH shim (an older router) — iptables-restore's
    # chain declaration must empty an existing chain in each
    shim = tempfile.mkdtemp(prefix="swgfence-legacy-")
    for t in ("iptables", "iptables-restore", "iptables-save"):
        os.symlink("/usr/sbin/" + t.replace("iptables", "iptables-legacy", 1), os.path.join(shim, t))
    os.chmod(shim, 0o755)
    arms = [("nft", "", "DROP"), ("nft", "", "ACCEPT")] + ([("legacy", shim + ":", "ACCEPT")] if os.path.exists("/usr/sbin/iptables-legacy-restore") else [])
    for be, pre, pol in arms:
        env = ["env", "PID=%d" % os.getpid(), "TAG=" + TAG, "ADDR=" + ADDR, "POLICY=" + pol, "CMDS=" + (cmds or "false"),
               "PATH=" + pre + "/usr/sbin:/usr/bin:/sbin:/bin"]
        pol = pol if be == "nft" else pol + " (iptables-legacy)"
        out = run_rig(sd + env + ["bash", "-c", RIG.replace("$$PID", "$PID")], 120)[0]
        got = dict(l.split(": ", 1) for l in out.splitlines() if ": " in l)
        check("[2] FORWARD %s: the commands run as shown" % pol, got.get("cmds") == "ok", out)
        check("[2] FORWARD %s: …and pasted again, they run again and add no rule (s9d-f8-lan F7)" % pol,
              got.get("again") == "ok" and got.get("rules") == "same", (got.get("again"), got.get("rules")))
        for d, w in WANT.items():
            check("[2] FORWARD %s: %s %s is %s" % (pol, SEEN[d], d, w), got.get(d) == w, got.get(d))
        check("[2] FORWARD %s: TCP to the internet gets through, from the router's address (masqueraded)" % pol,
              got.get("tcp") == "from 198.51.100.2", got.get("tcp"))
    shutil.rmtree(shim, ignore_errors=True)

SRC = open(SPA).read()
if "--perturb" in sys.argv:
    plants = {
        "the private ranges not dropped": ("-d 10.0.0.0/8,100.64.0.0/10,169.254.0.0/16,172.16.0.0/12,192.168.0.0/16 -j DROP",
                                           "-d 198.51.100.250 -j DROP"),
        "the chain's rest accepted, not dropped": ("\\n-A ${tag}-fwd -j DROP\\n", "\\n-A ${tag}-fwd -j ACCEPT\\n"),
        "the chain's accept names no uplink": ("-A ${tag}-fwd -o $UPLINK -j ACCEPT", "-A ${tag}-fwd -j ACCEPT"),
        "no FORWARD jump to the chain (the tunnel left to the policy)": ("+ `iptables -C FORWARD -i ${tag} -j ${tag}-fwd 2>/dev/null || iptables -I FORWARD -i ${tag} -j ${tag}-fwd\\n`", "+ ``"),
        "no INPUT drop": ("+ `iptables -C INPUT -i ${tag} -m conntrack ! --ctstate RELATED,ESTABLISHED -j DROP 2>/dev/null || iptables -I INPUT -i ${tag} -m conntrack ! --ctstate RELATED,ESTABLISHED -j DROP\\n`", "+ ``"),
        "the chain appended to, not declared in the transaction (a second paste doubles it)": ("iptables-restore --noflush <<EOF\\n*filter\\n:${tag}-fwd - [0:0]\\n",
                                                                                              "iptables -N ${tag}-fwd 2>/dev/null || true\\niptables-restore --noflush <<EOF\\n*filter\\n"),
        "a rule added again on a second paste (no -C)": ("iptables -C FORWARD -i ${tag} -j ${tag}-fwd 2>/dev/null || iptables -I FORWARD -i ${tag} -j ${tag}-fwd", "iptables -I FORWARD -i ${tag} -j ${tag}-fwd"),
    }
    bad, skipped = [], []
    for name, (a, b) in plants.items():
        if SRC.count(a) != 1:
            print("PERTURB FAILED — anchor for %r not in js/screen-settings.js exactly once (found %d)" % (name, SRC.count(a))); sys.exit(1)
        FAILS.clear(); SKIPS.clear()
        print("-- plant: " + name)
        run_checks(SRC.replace(a, b))
        if not any(f.startswith("[2]") for f in FAILS):
            (skipped if "[2]" in SKIPS else bad).append(name)
    print()
    print("PERTURB FAILED — stayed green: " + ", ".join(bad) if bad else
          "PERTURB OK — every plant that could run turned its check red; SKIPPED (needs root or `sudo -n`): "
          + ", ".join(skipped) if skipped else "PERTURB OK — every plant turned its check red")
    sys.exit(1 if bad else 0)

run_checks(SRC)
print()
print(("ALL PASS" + (" — SKIPPED: %s (needs root or `sudo -n`)" % ", ".join(SKIPS) if SKIPS else "")) if not FAILS
      else "%d FAIL" % len(FAILS))
sys.exit(1 if FAILS else 0)
