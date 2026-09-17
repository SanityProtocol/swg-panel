#!/bin/bash
# Self-test — update.sh moves AWG interfaces off the userspace fallback ONLY when that is what they are
# (docs/AWG-DATAPATH-RESILIENCE-PLAN.md D3). Sandboxed: the function is taken from update.sh with /sys/class/net and the
# conf dirs pointed at a temp tree; systemctl / modprobe / awg-quick are stubs that record what they were asked.
#   [1] module still missing → nothing is touched      [2] a kernel device → untouched
#   [3] a tun with no AmneziaWG conf (csqtt) → untouched  [4] tun + conf + ACTIVE unit → stop, then start the unit
#   [5] INACTIVE unit (created by the agent) → awg-quick down, then started THROUGH THE UNIT (a oneshot updater kills plain
#       children); [5b] no systemd → plain awg-quick up
#   [6] a lingering userspace instance (socket + process) is ended and its socket removed before the start;
#       [6b] pgrep/pkill look in this network namespace only (a container's own amneziawg-go awg0 is not ours)
#   [7] a bring-up that leaves no device is reported as down, not as "still on userspace"
#   [8] an exit device is only taken down — swg-noded brings it back up; [8b] a tun exit amneziawg-go does not serve → untouched
#   [9] a configuration the kernel refuses (tried on a throwaway device) → untouched and warned; [9b] the probe device is
#       deleted and never carries the live ListenPort
# Run: bash tests/awg_back_on_kernel_selftest.sh     --perturb drops the conf check, the unit start, the exit's amneziawg-go
#      test and the kernel probe; expects RED on [3], [5], [8b], [9].
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
fn="$(awk '/^awg_kernel_takes\(\)\{/,/^}$/' "$ROOT/update.sh"; awk '/^ensure_awg_back_on_kernel\(\)\{/,/^}$/' "$ROOT/update.sh")"
[ -n "$fn" ] || { echo "  FAIL function not found in update.sh"; exit 1; }
fn="${fn//\/sys\/class\/net/$T/sys}"; fn="${fn//\/etc\/amnezia\/amneziawg/$T/etc-awg}"; fn="${fn//\/etc\/amneziawg/$T/etc-awg2}"; fn="${fn//\/var\/run\/amneziawg/$T/run}"
[ "${1:-}" = "--perturb" ] && fn="${fn//\[ -n \"\$conf\" \] || continue/:}"
[ "${1:-}" = "--perturb" ] && fn="$(printf '%s\n' "$fn" | sed -e 's/if have systemctl; then run systemctl start/if false; then run systemctl start/' -e '/\[ -S "\$sock" \] || pgrep/s/.*/      :/' -e 's/awg_kernel_takes "\$conf" ||/true ||/')"
mkdir -p "$T/bin"
cat > "$T/bin/modprobe" <<'EOF'
#!/bin/sh
[ -e "$SBX/module-ok" ]
EOF
cat > "$T/bin/systemctl" <<'EOF'
#!/bin/sh
echo "systemctl $*" >> "$SBX/calls"
n=$(echo "${3:-$2}" | sed 's/awg-quick@//')
case "$1" in
  is-active) [ -e "$SBX/active-$n" ];;
  start) [ -S "$SBX/run/$n.sock" ] && echo "START-WHILE-SOCKET $n" >> "$SBX/calls"
         [ -e "$SBX/fail-up-$n" ] && { rm -rf "$SBX/sys/$n"; exit 1; }
         rm -f "$SBX/sys/$n/tun_flags";;
esac
EOF
cat > "$T/bin/awg-quick" <<'EOF'
#!/bin/sh
[ "$1" = strip ] && { printf '[Interface]\nPrivateKey = x\nListenPort = 51820\n\n[Peer]\nPublicKey = y\n'; exit 0; }
echo "awg-quick $*" >> "$SBX/calls"
n=$(basename "$2" .conf)
if [ "$1" = up ]; then
  [ -S "$SBX/run/$n.sock" ] && echo "UP-WHILE-SOCKET $n" >> "$SBX/calls"
  [ -e "$SBX/fail-up-$n" ] && { rm -rf "$SBX/sys/$n"; exit 1; }
  rm -f "$SBX/sys/$n/tun_flags"
fi
exit 0
EOF
cat > "$T/bin/pgrep" <<'EOF'
#!/bin/sh
for a; do p="$a"; done; echo "pgrep $*" >> "$SBX/ps-args"; n=$(echo "$p" | sed 's/^amneziawg-go //; s/\$$//'); [ -e "$SBX/proc-$n" ]
EOF
cat > "$T/bin/pkill" <<'EOF'
#!/bin/sh
for a; do p="$a"; done; echo "pkill $*" >> "$SBX/ps-args"; n=$(echo "$p" | sed 's/^amneziawg-go //; s/\$$//'); echo "pkill $n" >> "$SBX/calls"; rm -f "$SBX/proc-$n"
EOF
printf '#!/bin/sh\nexit 0\n' > "$T/bin/sleep"
cat > "$T/bin/ip" <<'EOF'
#!/bin/sh
echo "ip $*" >> "$SBX/probe"
[ "$1 $2" = "link add" ] && [ -e "$SBX/no-kernel-link" ] && exit 2
exit 0
EOF
cat > "$T/bin/awg" <<'EOF'
#!/bin/sh
[ "$1" = setconf ] && { cp "$3" "$SBX/probe-conf"; [ -e "$SBX/refuse-conf" ] && exit 1; }
exit 0
EOF
chmod +x "$T/bin/"*
run(){ "$@"; }; have(){ command -v "$1" >/dev/null 2>&1; }; ok(){ :; }; note(){ :; }; warn(){ echo "WARN $*" >> "$T/calls"; }; DID_FAIL=no
export SBX="$T" PATH="$T/bin:$PATH" SWG_NODED_STATE="$T/noded"; HAVE_BNODE=yes; DRYRUN=false; DID_UPDATE=no
eval "$fn"
setup(){ rm -rf "$T/sys" "$T/etc-awg" "$T/etc-awg2" "$T/run" "$T/noded" "$T/calls" "$T"/active-* "$T"/proc-* "$T"/fail-up-* "$T/module-ok" "$T/probe" "$T/probe-conf" "$T/refuse-conf" "$T/no-kernel-link" "$T/ps-args"; mkdir -p "$T/sys" "$T/etc-awg" "$T/etc-awg2" "$T/run"; : > "$T/calls"; }
sock(){ python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' "$T/run/$1.sock"; }
tun(){ mkdir -p "$T/sys/$1"; : > "$T/sys/$1/tun_flags"; }
kern(){ mkdir -p "$T/sys/$1"; }
setup; tun awg0; : > "$T/etc-awg/awg0.conf"; : > "$T/active-awg0"
ensure_awg_back_on_kernel; check "[1] module missing → nothing" "$([ ! -s "$T/calls" ]; echo $?)" "$(cat "$T/calls")"
setup; : > "$T/module-ok"; kern awg1; : > "$T/etc-awg/awg1.conf"; : > "$T/active-awg1"
ensure_awg_back_on_kernel; check "[2] kernel device → untouched" "$([ ! -s "$T/calls" ]; echo $?)" "$(cat "$T/calls")"
setup; : > "$T/module-ok"; tun csqtt1
ensure_awg_back_on_kernel; check "[3] tun without an AmneziaWG conf → untouched" "$(! grep -q csqtt1 "$T/calls"; echo $?)" "$(cat "$T/calls")"
setup; : > "$T/module-ok"; tun awg0; : > "$T/etc-awg/awg0.conf"; : > "$T/active-awg0"
ensure_awg_back_on_kernel; check "[4] active unit → stop, then start (never while its socket lingers)" "$(grep -qx 'systemctl stop awg-quick@awg0' "$T/calls" && grep -qx 'systemctl start awg-quick@awg0' "$T/calls" && ! grep -q WHILE-SOCKET "$T/calls"; echo $?)" "$(cat "$T/calls")"
setup; : > "$T/module-ok"; tun awg2; : > "$T/etc-awg2/awg2.conf"
ensure_awg_back_on_kernel
check "[5] inactive unit (agent-created) → awg-quick down, then STARTED THROUGH THE UNIT" "$(grep -q "awg-quick down .*awg2.conf" "$T/calls" && grep -qx 'systemctl start awg-quick@awg2' "$T/calls" && ! grep -q "awg-quick up" "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [5b] no systemd at all → the plain bring-up
setup; : > "$T/module-ok"; tun awg5; : > "$T/etc-awg/awg5.conf"
have(){ [ "$1" = systemctl ] && return 1; command -v "$1" >/dev/null 2>&1; }
ensure_awg_back_on_kernel
have(){ command -v "$1" >/dev/null 2>&1; }
check "[5b] no systemctl → awg-quick up" "$(grep -q "awg-quick up .*awg5.conf" "$T/calls" && ! grep -q 'systemctl' "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [6] the old userspace instance lingers (socket + process): it is ended and its socket removed BEFORE `up`
setup; : > "$T/module-ok"; tun awg3; : > "$T/etc-awg/awg3.conf"; sock awg3; : > "$T/proc-awg3"
ensure_awg_back_on_kernel
check "[6] lingering socket/process cleaned before up" "$(grep -qx 'pkill awg3' "$T/calls" && ! grep -q 'UP-WHILE-SOCKET awg3' "$T/calls" && [ ! -S "$T/run/awg3.sock" ]; echo $?)" "$(cat "$T/calls")"
check "[6b] every pgrep/pkill is limited to this network namespace" "$([ -s "$T/ps-args" ] && ! grep -v -- '--ns [0-9]* --nslist net -f ' "$T/ps-args" | grep -q .; echo $?)" "$(cat "$T/ps-args")"
# [7] the kernel bring-up fails and the device is gone: reported as DOWN, loudly
setup; : > "$T/module-ok"; tun awg4; : > "$T/etc-awg/awg4.conf"; : > "$T/fail-up-awg4"
ensure_awg_back_on_kernel
check "[7] an interface that did not come back is reported down" "$(grep -q 'WARN .*did not come back.* awg4' "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [8] an EXIT device on the fallback: taken down only — swg-noded brings it back; never started here
setup; : > "$T/module-ok"; tun wgx-1; mkdir -p "$T/noded/exits"; : > "$T/noded/exits/wgx-1.conf"; : > "$T/proc-wgx-1"
ensure_awg_back_on_kernel
check "[8] exit device → awg-quick down on its own conf, no start/up" "$(grep -q "awg-quick down .*noded/exits/wgx-1.conf" "$T/calls" && ! grep -qE "systemctl (start|stop) awg-quick@wgx-1|awg-quick up .*wgx-1" "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [8b] a tun exit amneziawg-go does NOT serve (an operator's wireguard-go, a device exit) → untouched
setup; : > "$T/module-ok"; tun wgx-2; mkdir -p "$T/noded/exits"; : > "$T/noded/exits/wgx-2.conf"
ensure_awg_back_on_kernel
check "[8b] tun exit with no amneziawg-go → untouched" "$(! grep -q wgx-2 "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [9] the kernel refuses this interface's configuration: nothing is stopped, and it is said
setup; : > "$T/module-ok"; tun awg6; : > "$T/etc-awg/awg6.conf"; : > "$T/active-awg6"; : > "$T/refuse-conf"
ensure_awg_back_on_kernel
check "[9] kernel refuses the conf → untouched, warned" "$(! grep -qE 'systemctl (stop|start) awg-quick@awg6|awg-quick (down|up) .*awg6|pkill awg6' "$T/calls" && grep -q 'WARN .* awg6 .*does not accept' "$T/calls"; echo $?)" "$(cat "$T/calls")"
setup; : > "$T/module-ok"; tun awg7; : > "$T/etc-awg/awg7.conf"; : > "$T/no-kernel-link"
ensure_awg_back_on_kernel
check "[9] no kernel link can be made at all → untouched" "$(grep -q 'WARN .* awg7 .*does not accept' "$T/calls" && ! grep -qE 'awg-quick (down|up) .*awg7|systemctl (stop|start) awg-quick@awg7' "$T/calls"; echo $?)" "$(cat "$T/calls")"
# [9b] a normal move: the probe device is deleted, and its conf never carries the live ListenPort
setup; : > "$T/module-ok"; tun awg8; : > "$T/etc-awg/awg8.conf"
ensure_awg_back_on_kernel
check "[9b] probe deleted, no ListenPort in the probe conf" "$(grep -q '^ip link add swgprobe' "$T/probe" && grep -q '^ip link del swgprobe' "$T/probe" && [ -s "$T/probe-conf" ] && ! grep -q ListenPort "$T/probe-conf" && grep -qx 'systemctl start awg-quick@awg8' "$T/calls"; echo $?)" "$(cat "$T/probe" "$T/calls")"
echo; [ "$FAILS" = 0 ] && echo "GREEN — 0 failed" || echo "RED — $FAILS failed"; [ "$FAILS" = 0 ]
