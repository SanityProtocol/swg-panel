#!/bin/bash
# Self-test — telling the panel about an update keeps the time it prints (lib/common.sh lc_emit_post). A panel address that
# DROPS packets cost every update ~3.4 min after "Update complete" while the loop said "up to 4s" / "up to 25s": it counted
# ATTEMPTS, each up to `--max-time 6` + 1 s (measured on a Debian VM 2026-09-18: a no-op update 207 s, 203 s of it these
# POSTs). A stub curl stands in for the panel: `hang` waits out its --max-time (curl exit 28), `refuse` fails at once
# (a restarting panel), `ok` answers, `slow` answers after 5 s (a node whose first nameserver is dead).
#   [1] hang, an in-progress state (6 s): gives up within the 6 s it prints, and says it could not reach the panel
#   [2] hang, a terminal state (25 s): gives up within 25 s, and its last attempt got only the time that was left
#   [3] refuse: still retried about once a second for the whole budget — a restarting panel is waited for as before
#   [4] ok: one POST, no waiting, nothing printed
#   [5] slow, both states: told on the FIRST POST, as before — the first attempt keeps its full 6 s (a lost `reinstalling`
#       is a key adoption no sync repeats)
# Run: bash tests/lc_emit_post_selftest.sh     --perturb gives every attempt a fixed --max-time 6 again, expects RED on [2].
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
# lc_emit_post ends on `  return 0; }`, not on a line of its own
src="$(awk '/^auth_curl\(\)\{/ {p=1} p {print} p && /^}$/ {exit}' "$ROOT/lib/common.sh")
$(awk '/^lc_emit_post\(\)\{/ {p=1} p {print} p && /^  return 0; }$/ {exit}' "$ROOT/lib/common.sh")"
[ "${1:-}" = "--perturb" ] && src="$(printf '%s\n' "$src" | sed -E 's/--max-time "[^"]*"/--max-time 6/')"
mkdir -p "$T/bin"
cat > "$T/bin/curl" <<'EOF'
#!/bin/bash
m=6; while [ $# -gt 0 ]; do [ "$1" = --max-time ] && { m="$2"; shift; }; shift; done
echo "max=$m" >> "$SBX/calls"
case "$(cat "$SBX/mode")" in ok) exit 0 ;; refuse) exit 7 ;; hang) sleep "$m"; exit 28 ;;
  slow) [ "$m" -ge 5 ] && { sleep 5; exit 0; }; sleep "$m"; exit 28 ;; esac
EOF
chmod +x "$T/bin/curl"; export PATH="$T/bin:$PATH"
eval "$src"
LC_URL=https://panel.invalid:8443; LC_TOKEN=tok; LC_VERIFY=no
run(){ # <name> <mode> <state> — the POST under a hard stop, so the old loop's minutes show as a failure, not a stall
  local d="$T/$1"; mkdir -p "$d"; echo "$2" > "$d/mode"; : > "$d/calls"
  local s; s=$(date +%s%N)
  SBX="$d" timeout 60 bash -c "$(declare -f auth_curl lc_emit_post); LC_URL=$LC_URL LC_TOKEN=$LC_TOKEN LC_VERIFY=$LC_VERIFY; lc_emit_post $3" > "$d/out" 2>&1
  echo $(( ($(date +%s%N) - s) / 1000000 )) > "$d/ms"; }
# every case runs side by side (the terminal ones take up to their full 25 s)
run hang6 hang updating & run hang25 hang updated & run refuse refuse updating & run ok ok updated &
run slow6 slow reinstalling & run slow25 slow updated & wait
ms(){ cat "$T/$1/ms"; }; n(){ grep -c . "$T/$1/calls"; }
check "[1] hang, in-progress: gave up within 6 s (+1 s slack) and said so" "$([ "$(ms hang6)" -le 7000 ] && grep -q "couldn't reach the panel" "$T/hang6/out"; echo $?)" "took $(ms hang6) ms, $(n hang6) POSTs: $(tr '\n' ' ' < "$T/hang6/calls")"
check "[2] hang, terminal: gave up within 25 s (+1 s slack)" "$([ "$(ms hang25)" -le 26000 ]; echo $?)" "took $(ms hang25) ms, $(n hang25) POSTs: $(tr '\n' ' ' < "$T/hang25/calls")"
check "[2] …and its last attempt got only the time that was left" "$([ "$(tail -1 "$T/hang25/calls" | cut -d= -f2)" -lt 6 ]; echo $?)" "$(tr '\n' ' ' < "$T/hang25/calls")"
check "[3] refuse: retried about once a second for the 6 s (5–7 POSTs), then gave up" "$(c=$(n refuse); [ "$c" -ge 5 ] && [ "$c" -le 7 ] && [ "$(ms refuse)" -le 7000 ]; echo $?)" "$(n refuse) POSTs in $(ms refuse) ms"
for x in slow6 slow25; do
  check "[5] slow ($x): told on the first POST, nothing printed" "$([ "$(n $x)" = 1 ] && [ ! -s "$T/$x/out" ]; echo $?)" "$(n $x) POSTs in $(ms $x) ms: $(tr '\n' ' ' < "$T/$x/calls") $(cat "$T/$x/out")"
done
check "[4] ok: one POST, no wait, nothing printed" "$([ "$(n ok)" = 1 ] && [ "$(ms ok)" -lt 1000 ] && [ ! -s "$T/ok/out" ]; echo $?)" "$(n ok) POSTs in $(ms ok) ms: $(cat "$T/ok/out")"
echo; [ "$FAILS" = 0 ] && echo "GREEN — 0 failed" || echo "RED — $FAILS failed"; [ "$FAILS" = 0 ]
