#!/bin/bash
# Self-test — an exit's .conf vs the distribution's wg-quick AppArmor profile (1.8.12 item 14, a user's report 2026-11-14).
# From apparmor 4.1 (Ubuntu 25.04 on) `wg-quick` is confined to /etc/wireguard, and swg-noded keeps every exit's .conf in
# <state>/exits, so every WARP / WireGuard exit died at "wg-quick: line 40: …/exits/wgx-….conf: Permission denied"
# (reproduced on a 26.04.1 guest: apparmor="DENIED" operation="open" profile="wg-quick" … denied_mask="r").
# lib/common.sh's ensure_wg_apparmor runs for real against a sandboxed /etc/apparmor.d, apparmor_parser a stub that records:
#   [1] wg-quick enforcing + <local/wg-quick> included → local/wg-quick carries the read-only exits block, the profile reloaded
#   [2] a second run writes nothing more (one block) and reloads again (present is not loaded)
#   [3] SWG_NODED_STATE moves the node's state → the block names that directory; behind a symlink → its RESOLVED path
#       (AppArmor mediates the real path, and wg-quick readlink -f's the .conf) — review F1
#   [2b] a block already there with other content (an older release, a moved state dir) is rewritten, once — review F3
#   [2c] a begin marker with no end after it → the file is left alone, the operator's lines kept, a warning — verify F11
#   [2d] a dry run says it would refresh a block that differs, and changes nothing — verify F14
#   [4] complain mode, no profile loaded, or no <local/wg-quick> include → no file written (the last one prints the block)
#   [5] wg and wg-quick both enforcing → each gets ITS block: sockets in local/wg, the exits in local/wg-quick, never crossed
#   [6] uninstall.sh's reap (its own loop, run) removes the wg-quick span, the file it created, and reloads the profile
#   [7] swg-noded names the refusal: exit_aa_refused() on the guest's own stderr and on the resolved path (F2), only while a
#       wg-quick profile is enforcing (F6), not on other failures; the sentence is under the 160 the error is cut at and has
#       a Russian line (the panel translates it as a key)
# Run: bash tests/apparmor_wgquick_selftest.sh
#      --perturb-wgq    the loop back to `wg awg` (no wg-quick)          expects RED on [1] [2] [3] [5]
#      --perturb-block  wg-quick given the socket block                  expects RED on [1] [5]
#      --perturb-noded  exit_aa_refused never matches                     expects RED on [7]
#      --perturb-resolve the block names the state dir unresolved        expects RED on [3]
#      --perturb-stale  a block present with other content is kept       expects RED on [2b]
#      --perturb-pair   the begin/end pairing check skipped               expects RED on [2c]
#      --perturb-enforce noded claims AppArmor with no wg-quick profile   expects RED on [7]
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
P="${1:-}"
LIB="$T/common.sh"; cp "$ROOT/lib/common.sh" "$LIB"; NODED="$T/swg-noded"; cp "$ROOT/swg-noded" "$NODED"
plant(){ python3 - "$1" "$2" "$3" <<'PY' || { echo "  STALE PERTURBATION — $4: anchor missing, this run would FALSE-PASS"; exit 3; }
import sys
f, a, b = sys.argv[1:4]; s = open(f).read()
if s.count(a) != 1: sys.exit(1)
open(f, "w").write(s.replace(a, b))
PY
}
case "$P" in
  --perturb-wgq)   plant "$LIB" '  for t in wg awg wg-quick; do' '  for t in wg awg; do' wgq ;;
  --perturb-block) plant "$LIB" '    if [ "$t" = wg-quick ]; then block="$(apparmor_wgq_block)";' '    if [ "$t" = wg-quick ]; then block="$APPARMOR_LOCAL_BLOCK";' block ;;
  --perturb-noded) plant "$NODED" '    if not any(re.search(re.escape(d)' '    if True or not any(re.search(re.escape(d)' noded ;;
  --perturb-resolve) plant "$LIB" '  d="$(readlink -m "$s" 2>/dev/null)"; d="${d:-$s}/exits"' '  d="$s/exits"' resolve ;;
  --perturb-stale) plant "$LIB" '      sed -i "\|$APPARMOR_LOCAL_BEGIN|,\|$APPARMOR_LOCAL_END|d" "$loc" 2>/dev/null \' '      true \' stale ;;
  --perturb-pair) plant "$LIB" '             END { exit (bad || o) ? 1 : 0 }' '             END { exit 0 }' pair ;;
  --perturb-enforce) plant "$NODED" '            return any(re.match(' '            return True or any(re.match(' enforce ;;
  "") ;;
  *) echo "unknown $P"; exit 2 ;;
esac

mkdir -p "$T/bin"; cat > "$T/bin/apparmor_parser" <<'EOF'
#!/bin/sh
echo "$*" >> "$AA_LOG"
EOF
chmod +x "$T/bin/apparmor_parser"
# One sandbox per case: profiles loaded (+ their mode), which profile files exist, whether they include local/.
box(){   # box <name> <profiles text> <files: name:include|name:noinclude ...>
  local d="$T/$1"; rm -rf "$d"; mkdir -p "$d/aa/local"; printf '%b' "$2" > "$d/profiles"; : > "$d/log"; shift 2
  local f; for f in "$@"; do
    if [ "${f#*:}" = include ]; then printf 'profile %s {\n  include if exists <local/%s>\n}\n' "${f%%:*}" "${f%%:*}" > "$d/aa/${f%%:*}"
    else printf 'profile %s {\n}\n' "${f%%:*}" > "$d/aa/${f%%:*}"; fi
  done
}
run_ens(){   # run_ens <box> [env…] — the real ensure_wg_apparmor, sourced from the (maybe planted) lib
  local d="$T/$1"; shift
  env "$@" PATH="$T/bin:$PATH" AA_DIR="$d/aa" AA_PROFILES="$d/profiles" AA_LOG="$d/log" bash -c '
    source "$1" >/dev/null 2>&1
    warn(){ echo "WARN $*"; }; ok(){ :; }; sub(){ echo "SUB $*"; }; have(){ command -v "$1" >/dev/null 2>&1; }
    AA_DIR="$AA_DIR_X"; AA_PROFILES="$AA_PROFILES_X"; ensure_wg_apparmor' _ "$LIB" 2>&1
}
# lib/common.sh sets AA_DIR from the environment at source time; the _X copies survive its own defaults either way
run_box(){ local b="$1"; shift; AA_DIR_X="$T/$b/aa" AA_PROFILES_X="$T/$b/profiles" run_ens "$b" AA_DIR_X="$T/$b/aa" AA_PROFILES_X="$T/$b/profiles" "$@"; }
BEGIN='# --- swgPanel: userspace WireGuard datapaths (begin) ---'

echo "[1] wg-quick enforcing, local/ included → the exits block, the profile reloaded"
box b1 'wg-quick (enforce)\n' wg-quick:include
run_box b1 >/dev/null
L="$T/b1/aa/local/wg-quick"
grep -qxF '  /var/lib/swg-noded/exits/ r,' "$L" 2>/dev/null && grep -qxF '  /var/lib/swg-noded/exits/*.conf r,' "$L"; check "local/wg-quick grants the exits directory and its .conf files, read-only" $? "$(cat "$L" 2>/dev/null)"
! grep -q 'rw,\|/run/wireguard\|\*\*' "$L" 2>/dev/null; check "…and nothing wider (no rw, no **, no sockets)" $?
grep -qx -- "-r $T/b1/aa/wg-quick" "$T/b1/log"; check "the wg-quick profile is reloaded" $? "$(cat "$T/b1/log")"

echo "[2] a second run"
run_box b1 >/dev/null
[ "$(grep -cF "$BEGIN" "$L" 2>/dev/null)" = 1 ]; check "one block, not two" $? "$(grep -cF "$BEGIN" "$L" 2>/dev/null)"
[ "$(grep -cx -- "-r $T/b1/aa/wg-quick" "$T/b1/log")" = 2 ]; check "…reloaded again (present is not loaded)" $?

echo "[2b] a block already there with other content"
box b2 'wg-quick (enforce)\n' wg-quick:include
printf 'keep me\n  %s\n  /old/state/exits/*.conf r,\n%s\n' "$BEGIN" '  # --- swgPanel: userspace WireGuard datapaths (end) ---' > "$T/b2/aa/local/wg-quick"
run_box b2 >/dev/null
grep -qxF '  /var/lib/swg-noded/exits/*.conf r,' "$T/b2/aa/local/wg-quick" && ! grep -q '/old/state' "$T/b2/aa/local/wg-quick"; check "rewritten to the current grant (review F3)" $? "$(cat "$T/b2/aa/local/wg-quick")"
[ "$(grep -cF "$BEGIN" "$T/b2/aa/local/wg-quick")" = 1 ] && grep -qx 'keep me' "$T/b2/aa/local/wg-quick"; check "…one block, and what was not ours is kept" $?

echo "[2c] a begin marker with no end"
box b2c 'wg-quick (enforce)\n' wg-quick:include
printf '  %s\n  /old/state/exits/*.conf r,\n  /home/op/own/** r,\n  /srv/op-rule r,\n' "$BEGIN" > "$T/b2c/aa/local/wg-quick"
cp "$T/b2c/aa/local/wg-quick" "$T/b2c/before"
o="$(run_box b2c)"
cmp -s "$T/b2c/before" "$T/b2c/aa/local/wg-quick"; check "⚠️ the file is left exactly as it was — the operator's rules after it survive (verify F11)" $? "$(cat "$T/b2c/aa/local/wg-quick")"
printf '%s\n' "$o" | grep -q 'WARN.*without its end marker'; check "…and it says so" $? "$o"

echo "[2d] a dry run"
box b2d 'wg-quick (enforce)\n' wg-quick:include
printf '  %s\n  /old/state/exits/*.conf r,\n%s\n' "$BEGIN" '  # --- swgPanel: userspace WireGuard datapaths (end) ---' > "$T/b2d/aa/local/wg-quick"
cp "$T/b2d/aa/local/wg-quick" "$T/b2d/before"
o="$(run_box b2d DRYRUN=true)"
cmp -s "$T/b2d/before" "$T/b2d/aa/local/wg-quick" && printf '%s\n' "$o" | grep -q '\[skip\] refresh the swgPanel rules'; check "a dry run announces the refresh and changes nothing (verify F14)" $? "$o"

echo "[3] the node's state elsewhere"
box b3 'wg-quick (enforce)\n' wg-quick:include
run_box b3 SWG_NODED_STATE=/srv/swg-state >/dev/null
grep -qxF '  /srv/swg-state/exits/*.conf r,' "$T/b3/aa/local/wg-quick" 2>/dev/null; check "SWG_NODED_STATE=/srv/swg-state → the block names /srv/swg-state/exits" $? "$(cat "$T/b3/aa/local/wg-quick" 2>/dev/null)"
mkdir -p "$T/realstate"; ln -s "$T/realstate" "$T/linkstate"
box b3b 'wg-quick (enforce)\n' wg-quick:include
run_box b3b SWG_NODED_STATE="$T/linkstate" >/dev/null
grep -qxF "  $T/realstate/exits/*.conf r," "$T/b3b/aa/local/wg-quick" 2>/dev/null; check "a state dir behind a symlink → the RESOLVED path (review F1)" $? "$(cat "$T/b3b/aa/local/wg-quick" 2>/dev/null)"

echo "[4] where it must not write"
box b4a 'wg-quick (complain)\n' wg-quick:include; run_box b4a >/dev/null
[ ! -e "$T/b4a/aa/local/wg-quick" ]; check "complain mode → untouched" $?
box b4b 'wg (enforce)\n' wg-quick:include wg:include; run_box b4b >/dev/null
[ ! -e "$T/b4b/aa/local/wg-quick" ]; check "a wg-quick profile on disk but not loaded → untouched" $?
box b4c 'wg-quick (enforce)\n' wg-quick:noinclude; o="$(run_box b4c)"
[ ! -e "$T/b4c/aa/local/wg-quick" ] && ! grep -q -- "-r" "$T/b4c/log"; check "no <local/wg-quick> include → no file, no reload" $?
printf '%s\n' "$o" | grep -qF '/var/lib/swg-noded/exits/*.conf r,' && printf '%s\n' "$o" | grep -q 'WARN.*WARP / WireGuard exits will not come up'; check "…and it says why and prints the block to add" $? "$o"

echo "[5] wg and wg-quick both enforcing"
box b5 'wg (enforce)\nwg-quick (enforce)\n' wg:include wg-quick:include; run_box b5 >/dev/null
grep -q '/run/wireguard/\*.sock' "$T/b5/aa/local/wg" 2>/dev/null && ! grep -q 'exits' "$T/b5/aa/local/wg"; check "local/wg: the sockets, not the exits" $? "$(cat "$T/b5/aa/local/wg" 2>/dev/null)"
grep -q 'exits/\*.conf' "$T/b5/aa/local/wg-quick" 2>/dev/null && ! grep -q '/run/wireguard' "$T/b5/aa/local/wg-quick"; check "local/wg-quick: the exits, not the sockets" $? "$(cat "$T/b5/aa/local/wg-quick" 2>/dev/null)"

echo "[6] uninstall.sh's reap"
loop="$(sed -n '/^  for _aal in \/etc\/apparmor.d\/local\/\*; do/,/^  done/p' "$ROOT/uninstall.sh")"
[ -n "$loop" ]; check "found the reap loop in uninstall.sh" $?
loop="${loop//\/etc\/apparmor.d/$T/b5/aa}"
: > "$T/b5/log"
PATH="$T/bin:$PATH" AA_LOG="$T/b5/log" bash -c 'info(){ :; }; run(){ "$@"; }; rmrf(){ rm -rf "$@"; }; '"$loop" >/dev/null 2>&1
[ ! -e "$T/b5/aa/local/wg-quick" ]; check "the wg-quick grant is gone, and the file it created with it" $? "$(cat "$T/b5/aa/local/wg-quick" 2>/dev/null)"
grep -qx -- "-r $T/b5/aa/wg-quick" "$T/b5/log"; check "…and the wg-quick profile is reloaded" $? "$(cat "$T/b5/log")"

echo "[7] swg-noded names the refusal"
SWG_NO_REEXEC=1 python3 - "$NODED" "$ROOT/js/lang/ru.js" "$T" <<'PY'
import importlib.machinery, importlib.util, json, sys
ld = importlib.machinery.SourceFileLoader("swgnoded_aawgq", sys.argv[1])
m = importlib.util.module_from_spec(importlib.util.spec_from_loader("swgnoded_aawgq", ld))
try: ld.exec_module(m)
except SystemExit: pass
ru = open(sys.argv[2]).read()
real = "/usr/bin/wg-quick: line 40: %s/wgx-c6d79c86.conf: Permission denied\n" % m.EXIT_DIR   # the guest's own line
import os
T = sys.argv[3]
prof = os.path.join(T, "aa-profiles"); open(prof, "w").write("wg (enforce)\nwg-quick (enforce)\n")
m.AA_PROFILES_FILE = prof
fails = 0
def chk(name, ok):
    global fails
    print(("  PASS " if ok else "  FAIL ") + name); fails += 0 if ok else 1
chk("the guest's refusal of an exit .conf is recognised", m.exit_aa_refused(real))
chk("…not a refusal of something else (a tool wg-quick exec'd)", not m.exit_aa_refused("/usr/bin/wg-quick: line 32: /usr/bin/ip: Operation not permitted"))
chk("…not a conf outside the exits directory", not m.exit_aa_refused("/usr/bin/wg-quick: line 40: /etc/x/wgx-1.conf: Permission denied"))
chk("…not an empty error", not m.exit_aa_refused(""))
os.makedirs(os.path.join(T, "real-ex"), exist_ok=True)
if not os.path.lexists(os.path.join(T, "link-ex")): os.symlink(os.path.join(T, "real-ex"), os.path.join(T, "link-ex"))
keep = m.EXIT_DIR; m.EXIT_DIR = os.path.join(T, "link-ex")
chk("the path bash names is wg-quick's readlink -f of ours: the resolved exits dir counts too (review F2)",
    m.exit_aa_refused("/usr/bin/wg-quick: line 40: %s/wgx-1.conf: Permission denied" % os.path.join(T, "real-ex")))
m.EXIT_DIR = keep
open(prof, "w").write("wg (enforce)\nwg-quick (complain)\n")
chk("⚠️ no wg-quick profile enforcing → not AppArmor: the error keeps its own words (review F6)", not m.exit_aa_refused(real))
m.AA_PROFILES_FILE = os.path.join(T, "no-such-file")
chk("…and none readable → not claimed either", not m.exit_aa_refused(real))
open(prof, "w").write("/usr/bin/wg-quick (enforce)\n"); m.AA_PROFILES_FILE = prof
chk("a profile named by its path counts as enforcing", m.exit_aa_refused(real))
open(prof, "w").write("/bin/wg-quick (enforce)\n")
chk("…and by /bin, as lib/common.sh reads it (verify F12)", m.exit_aa_refused(real))
chk("the sentence fits the 160 the exit error is cut at (or T() misses it)", len(m.EXIT_AA_REFUSED) <= 160)
chk("…and has a Russian line", json.dumps(m.EXIT_AA_REFUSED, ensure_ascii=False) in ru)
chk("the bring-up uses it", "EXIT_AA_REFUSED if exit_aa_refused(r.stderr) else r.stderr" in open(sys.argv[1]).read())
sys.exit(1 if fails else 0)
PY
r=$?; [ $r = 0 ] || FAILS=$((FAILS+1))

echo
if [ -n "$P" ]; then
  [ "$FAILS" -gt 0 ] && { echo "PERTURB OK ($P) — $FAILS check(s) went red"; exit 1; }
  echo "PERTURB FAILED ($P) — the fix was removed and every check still passed"; exit 0
fi
[ "$FAILS" = 0 ] && { echo "ALL PASS"; exit 0; }
echo "$FAILS FAIL(S)"; exit 1
