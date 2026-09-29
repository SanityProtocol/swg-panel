#!/bin/bash
# Self-test — update.sh follows the amnezia packages to the PPA's build (docs/AWG31-LOAD-PLAN.md D1). Sandboxed: the
# functions are taken from update.sh; apt-get / apt-cache / dpkg-query / dpkg -S / modinfo / ip / modprobe are stubs that
# record what they were asked (dpkg --compare-versions is the real one).
#   [1] amneziawg-dkms not installed (source route, NixOS…) → nothing asked of apt
#   [2] the `awg` on PATH is not amneziawg-tools' (hand-built) → nothing upgraded
#   [3] the candidate is what is installed, or OLDER → nothing upgraded
#   [4] a newer build, kernel devices up → ONE transaction with dkms + tools (+ the metapackage), the module left loaded,
#       the output says it loads at the next reboot or from the panel
#   [5] a newer build, no device anywhere → the new module is loaded now (modprobe -r, then modprobe)
#   [6] a device in another named namespace → not reloaded (rmmod would destroy it there)
#   [7] only the amnezia source is refreshed, never the whole index; a run that already refreshed it does not again
#   [8] apt fails → a note, the update is not failed
#   [9] packages held (apt-mark hold) → left alone, said once, not an error
#  [10] no headers for the running kernel → not upgraded (the old module would go, the new could not build), warned
#  [11] the install waits for the dpkg lock rather than failing on it (unattended-upgrades)
#  [12] a device in a CONTAINER's namespace (not named, seen only through /proc) → not reloaded
#  [13] the automatic load unloaded the old module but the new one will not load → says the box runs on userspace
# Run: bash tests/awg_pkg_follow_selftest.sh     --perturb drops the tools-ownership check, the device check, the tools
#      from the transaction, the hold check, the headers check and the /proc scan; expects RED on [2] [4] [6] [9] [10] [12].
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
fn="$(grep -E '^(pkg_installed|pkg_candidate)\(\)\{.*\}' "$ROOT/update.sh"     # one-liners
      for f in awg_kdevs awg_kdevs_elsewhere awg_src_refresh ensure_awg_pkg_follow; do awk -v f="$f" '$0 ~ "^"f"\\(\\)\\{" {p=1} p {print} p && /^}$/ {exit}' "$ROOT/update.sh"; done)"
printf '%s\n' "$fn" | grep -q '^ensure_awg_pkg_follow' || { echo "  FAIL ensure_awg_pkg_follow not found in update.sh"; exit 1; }
fn="${fn//\/etc\/apt\/sources.list.d/$T/sld}"; fn="${fn//\/sys\/module\/amneziawg\/version/$T/loaded}"; fn="${fn//\/sys\/module\/amneziawg/$T/sysmod}"
fn="${fn//\/lib\/modules/$T/libmod}"; fn="${fn//\/proc\//$T/proc/}"
_planted(){ [ "$1" != "$2" ] || { echo "  STALE PERTURBATION — $3: its anchor is missing, nothing was planted, this run would FALSE-PASS"; exit 3; }; }
if [ "${1:-}" = "--perturb" ]; then
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's/in amneziawg-tools:\*) ;; \*) return 0 ;; esac/in *) ;; esac/')"; _planted "$_b" "$fn" "the tools-ownership check"
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's/if \[ -z "\$(awg_kdevs)" \] && \[ -z "\$(awg_kdevs_elsewhere)" \]; then/if true; then/')"; _planted "$_b" "$fn" "the device check"
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's/pk="amneziawg-dkms amneziawg-tools"/pk="amneziawg-dkms"/')"; _planted "$_b" "$fn" "the tools in the transaction"
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's/\*" amneziawg-dkms "\*|\*" amneziawg-tools "\*|\*" amneziawg "\*)/*" never-held "*)/')"; _planted "$_b" "$fn" "the hold check"
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's|if \[ ! -e "[^"]*/libmod/$(uname -r)/build" \]; then|if false; then|')"; _planted "$_b" "$fn" "the headers check"
  _b="$fn"; fn="$(printf '%s\n' "$fn" | sed -e 's|  have nsenter \|\| return 0|  return 0|')"; _planted "$_b" "$fn" "the /proc scan"
fi
mkdir -p "$T/bin" "$T/sld" "$T/usr-bin"
stub(){ printf '#!/bin/sh\n%s\n' "$2" > "$T/bin/$1"; chmod +x "$T/bin/$1"; }
stub apt-get 'echo "apt-get $*" >> "$SBX/calls"; case "$*" in *install*) [ -e "$SBX/apt-fail" ] && exit 100; cp "$SBX/cand" "$SBX/inst-amneziawg-dkms"; [ -e "$SBX/disk-after" ] && cp "$SBX/disk-after" "$SBX/disk";; esac; exit 0'
stub apt-cache 'printf "%s:\n  Installed: x\n  Candidate: %s\n" "$2" "$(cat "$SBX/cand")"'
stub dpkg-query 'f="$SBX/inst-${4:-$3}"; [ -e "$f" ] && cat "$f"; exit 0'
stub dpkg 'if [ "$1" = -S ]; then cat "$SBX/owner" 2>/dev/null; [ -s "$SBX/owner" ]; exit $?; fi; exec /usr/bin/dpkg "$@"'
stub modinfo 'cat "$SBX/disk"'
stub modprobe 'echo "modprobe $*" >> "$SBX/calls"; if [ "$1" = -r ]; then rm -rf "$SYSMOD"; exit 0; fi; [ -e "$SBX/load-fail" ] && exit 1; mkdir -p "$SYSMOD"; exit 0'
stub apt-mark 'cat "$SBX/held" 2>/dev/null; exit 0'
stub nsenter 'n="${1#--net=}"; shift; [ "$(readlink "$n")" = "net:[4026532999]" ] && [ -e "$SBX/ctr-dev" ] && echo "9: awg-ctr: <POINTOPOINT>"; exit 0'
stub uname 'echo 6.8.0-test'
stub ip 'case "$*" in "netns list") cat "$SBX/netns" 2>/dev/null;; "-n "*) [ -e "$SBX/ns-dev" ] && echo "7: e0: <POINTOPOINT> mtu 1420";; *type\ amneziawg*) cat "$SBX/kdevs" 2>/dev/null;; esac; exit 0'
printf '#!/bin/sh\n' > "$T/usr-bin/awg"; chmod +x "$T/usr-bin/awg"
cat > "$T/run.sh" <<EOF
HAVE_BNODE=yes; DRYRUN=false; APT_DONE=\${APT_DONE:-no}; DID_UPDATE=no; DID_FAIL=no
have(){ command -v "\$1" >/dev/null 2>&1; }; run(){ "\$@"; }
ok(){ echo "OK \$*"; }; warn(){ echo "WARN \$*"; }; note(){ echo "NOTE \$*"; }
$fn
AWG_PKG_ROUTE=no; ensure_awg_pkg_follow; echo "DID_UPDATE=\$DID_UPDATE DID_FAIL=\$DID_FAIL ROUTE=\$AWG_PKG_ROUTE"
EOF
case_(){   # case_ <name> : a fresh sandbox — 1.0 installed and loaded, 3.1 in the PPA, awg owned by amneziawg-tools
  export SBX="$T/$1"; rm -rf "$SBX"; mkdir -p "$SBX"; : > "$SBX/calls"
  echo "1.0.0-0~202603291904+ac946a9~ubuntu24.04.1" > "$SBX/inst-amneziawg-dkms"
  echo "1.0.20210914-0~202602231231+5d6179a~ubuntu24.04.1" > "$SBX/inst-amneziawg"
  echo "1.0.0-0~202609061402+4569c4c~ubuntu24.04.1" > "$SBX/cand"
  echo "amneziawg-tools: $T/usr-bin/awg" > "$SBX/owner"
  echo "1.0.20251009" > "$SBX/disk"; echo "3.1.20260812" > "$SBX/disk-after"; echo "1.0.20251009" > "$T/loaded"
  echo "5: awg0: <POINTOPOINT,NOARP,UP> mtu 1420" > "$SBX/kdevs"
  echo 'Types: deb' > "$T/sld/amnezia-ubuntu-ppa-noble.sources"
  export SYSMOD="$T/sysmod"; mkdir -p "$SYSMOD" "$T/libmod/6.8.0-test/build"
  rm -rf "$T/proc"; mkdir -p "$T/proc/self/ns" "$T/proc/1/ns" "$T/proc/4242/ns"
  ln -s "net:[4026531840]" "$T/proc/self/ns/net"; ln -s "net:[4026531840]" "$T/proc/1/ns/net"; ln -s "net:[4026532999]" "$T/proc/4242/ns/net"
}
go(){ PATH="$T/bin:$T/usr-bin:/usr/bin:/bin" bash "$T/run.sh" 2>&1; }

echo; echo "[1] no amneziawg-dkms"
case_ c1; rm "$SBX/inst-amneziawg-dkms"; out="$(go)"
check "nothing asked of apt" "$([ ! -s "$SBX/calls" ] && echo 0 || echo 1)" "$(cat "$SBX/calls")"

echo; echo "[2] hand-built awg"
case_ c2; : > "$SBX/owner"; out="$(go)"
check "nothing upgraded" "$(grep -q install "$SBX/calls" && echo 1 || echo 0)" "$(cat "$SBX/calls")"
check "…and not recorded as the package route" "$(printf '%s' "$out" | grep -q 'ROUTE=no' && echo 0 || echo 1)" "$out"

echo; echo "[3] nothing newer"
case_ c3; cp "$SBX/inst-amneziawg-dkms" "$SBX/cand"; out="$(go)"
check "the same build → nothing upgraded" "$(grep -q install "$SBX/calls" && echo 1 || echo 0)"
case_ c3b; echo "1.0.0-0~202601011111+000000~ubuntu24.04.1" > "$SBX/cand"; out="$(go)"
check "an OLDER candidate → nothing upgraded" "$(grep -q install "$SBX/calls" && echo 1 || echo 0)"

echo; echo "[4] newer build, devices up"
case_ c4; out="$(go)"
check "one transaction: dkms + tools + the metapackage" "$(grep -c 'install -y .*--only-upgrade amneziawg-dkms amneziawg-tools amneziawg$' "$SBX/calls" | grep -qx 1 && echo 0 || echo 1)" "$(cat "$SBX/calls")"
check "the loaded module is left alone" "$(grep -q 'modprobe -r' "$SBX/calls" && echo 1 || echo 0)"
check "the output says: next reboot, or from the panel" "$(printf '%s' "$out" | grep -q 'until the next reboot, or load it now from the panel' && echo 0 || echo 1)" "$out"
check "counted as an update, not a failure" "$(printf '%s' "$out" | grep -q 'DID_UPDATE=yes DID_FAIL=no' && echo 0 || echo 1)"
check "…and the package route recorded (the later summary line says the module and tools follow the PPA)" "$(printf '%s' "$out" | grep -q 'ROUTE=yes' && echo 0 || echo 1)"

echo; echo "[5] newer build, no device"
case_ c5; : > "$SBX/kdevs"; out="$(go)"
check "the new module is loaded now" "$(grep -q 'modprobe -r amneziawg' "$SBX/calls" && grep -q '^modprobe amneziawg' "$SBX/calls" && echo 0 || echo 1)" "$(cat "$SBX/calls")"
check "…and says so" "$(printf '%s' "$out" | grep -q 'installed and loaded' && echo 0 || echo 1)" "$out"

echo; echo "[6] a device in another namespace"
case_ c6; : > "$SBX/kdevs"; echo "ve" > "$SBX/netns"; touch "$SBX/ns-dev"; out="$(go)"
check "not reloaded" "$(grep -q 'modprobe -r' "$SBX/calls" && echo 1 || echo 0)" "$(cat "$SBX/calls")"

echo; echo "[7] the refresh"
case_ c7; out="$(go)"
check "only the amnezia source is refreshed" "$(grep 'apt-get update' "$SBX/calls" | grep -q 'sourcelist=/dev/null' && grep -q 'sourceparts=' "$SBX/calls" && echo 0 || echo 1)" "$(cat "$SBX/calls")"
case_ c7b; out="$(APT_DONE=yes go)"
check "an index refreshed earlier in the run is not refreshed again" "$(grep -q 'apt-get update' "$SBX/calls" && echo 1 || echo 0)"

echo; echo "[8] apt fails"
case_ c8; touch "$SBX/apt-fail"; out="$(go)"
check "a note, not a failed update" "$(printf '%s' "$out" | grep -q 'NOTE AmneziaWG: the package upgrade did not go through' && printf '%s' "$out" | grep -q 'DID_FAIL=no' && echo 0 || echo 1)" "$out"

echo; echo "[9] held"
case_ c9; echo "amneziawg-dkms" > "$SBX/held"; out="$(go)"
check "nothing upgraded, said once" "$( ! grep -q 'install -y' "$SBX/calls" && printf '%s' "$out" | grep -q 'they are held' && echo 0 || echo 1)" "$out"
check "…not an error" "$(printf '%s' "$out" | grep -q 'WARN' && echo 1 || echo 0)" "$out"

echo; echo "[10] no headers for this kernel"
case_ c10; rm -rf "$T/libmod/6.8.0-test/build"; out="$(go)"
check "not upgraded, warned with the way out" "$( ! grep -q 'install -y' "$SBX/calls" && printf '%s' "$out" | grep -q 'WARN.*headers for this kernel.*install linux-headers' && echo 0 || echo 1)" "$out"

echo; echo "[11] the dpkg lock"
case_ c11; out="$(go)"
check "the install waits for the lock" "$(grep 'install -y' "$SBX/calls" | grep -q 'DPkg::Lock::Timeout=' && echo 0 || echo 1)" "$(cat "$SBX/calls")"

echo; echo "[12] a device in a container's namespace"
case_ c12; : > "$SBX/kdevs"; touch "$SBX/ctr-dev"; out="$(go)"
check "not reloaded" "$(grep -q 'modprobe -r' "$SBX/calls" && echo 1 || echo 0)" "$(cat "$SBX/calls")"

echo; echo "[13] the new module will not load"
case_ c13; : > "$SBX/kdevs"; touch "$SBX/load-fail"; out="$(go)"
check "says the box runs on the userspace fallback (not that the old module stays)" "$(printf '%s' "$out" | grep -q 'userspace fallback until it does' && echo 0 || echo 1)" "$out"

echo
if [ "${1:-}" = "--perturb" ]; then [ "$FAILS" -gt 0 ] && { echo "perturb: RED as it must be ($FAILS)"; exit 0; } || { echo "perturb: NOT CAUGHT"; exit 1; }; fi
[ "$FAILS" = 0 ] && echo "ALL PASS" || echo "FAIL: $FAILS"; exit $((FAILS > 0))
