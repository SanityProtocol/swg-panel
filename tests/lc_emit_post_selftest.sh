#!/bin/bash
# Self-test — telling the panel about an update keeps the time it prints (lib/common.sh lc_emit_post). A panel address that
# DROPS packets cost every update ~3.4 min after "Update complete" while the loop said "up to 4s" / "up to 25s": it counted
# ATTEMPTS, each up to `--max-time 6` + 1 s (measured on a Debian VM 2026-09-18: a no-op update 207 s, 203 s of it these
# POSTs). A stub panel_req stands in for the panel (lc_emit_post sends through it — the node's trust on the connection the
# token goes out on; panel_req_selftest.py tests it on the wire): `hang` waits out its timeout, `refuse` fails at once
# (a restarting panel), `ok` answers, `slow` answers after 5 s (a node whose first nameserver is dead), `pin` = the panel
# failed the node's trust (panel_req exit 4: nothing was sent).
#   [1] hang, an in-progress state (6 s): gives up within the 6 s it prints, and says it could not reach the panel
#   [2] hang, a terminal state (25 s): gives up within 25 s, and its last attempt got only the time that was left
#   [3] refuse: still retried about once a second for the whole budget — a restarting panel is waited for as before
#   [4] ok: one POST, no waiting, nothing printed
#   [5] slow, both states: told on the FIRST POST, as before — the first attempt keeps its full 6 s (a lost `reinstalling`
#       is a key adoption no sync repeats)
#   [6] pin: ONE attempt, no retry, one line saying why and that the token goes nowhere else — and the NEXT status of the
#       run (the EXIT trap's terminal one) is not attempted at all (1.8.8 qualification, round 6: both went out, curl -k)
#   [7] the node's trust reaches panel_req: LC_VERIFY and LC_FP are what it is handed
#   [8] (round 8) a panel that ANSWERED every attempt with an error is not "couldn't reach the panel": HTTP 401 → it says the
#       panel does not accept this node's key; HTTP 500 → it says what it answered
#   [9] (round 10, N13) a REFUSAL is an answer, not an outage: HTTP 401 / 403 → ONE attempt, no "telling the panel … up to
#       25s" line, no waiting — it was asked again about once a second for the whole budget; HTTP 500 (a panel mid-restart
#       may answer one) is still retried
# Run: bash tests/lc_emit_post_selftest.sh     --perturb gives every attempt a fixed timeout of 6 again, expects RED on [2];
#      --perturb-pin retries a refused trust like any failure (and the next status goes out), expects RED on [6];
#      --perturb-fp hands panel_req no pin, expects RED on [7];
#      --perturb-text says "couldn't reach the panel" whatever it answered (the shipped text), expects RED on [8];
#      --perturb-refusal retries a 401/403 for the whole budget again, expects RED on [9].
# Every perturbation must change the lifted function: one whose sed matched nothing stops here, RED (a dead one never reads green).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAILS=0; check(){ if [ "$2" = 0 ]; then echo "  PASS $1"; else echo "  FAIL $1 ${3:-}"; FAILS=$((FAILS+1)); fi; }
# lc_emit_post ends on `  return 0; }`, not on a line of its own
src="$(awk '/^lc_emit_post\(\)\{/ {p=1} p {print} p && /^  return 0; }$/ {exit}' "$ROOT/lib/common.sh")"
src0="$src"
case "${1:-}" in
  --perturb)     src="$(printf '%s\n' "$src" | sed -E 's/"\$\(\( _left < 6 \? _left : 6 \)\)"/6/')";;
  --perturb-pin) src="$(printf '%s\n' "$src" | sed -E 's/if \[ "\$_rc" = 4 \]; then LC_WITHHELD=1/if false; then LC_WITHHELD=1/; s/^  \[ -n "\$\{LC_WITHHELD:-\}" \] \&\& return 0$/  :/')";;
  --perturb-fp)  src="$(printf '%s\n' "$src" | sed -E 's/"\$\{LC_FP:-\}"/""/')";;
  --perturb-text) src="$(printf '%s\n' "$src" | sed -E 's/^    "3:HTTP 401"\|"3:HTTP 403"\)$/    never1)/; s/^    3:\*\) echo/    never2) echo/')";;
  --perturb-refusal) src="$(printf '%s\n' "$src" | sed -E 's/^    case "\$_rc:\$_why" in "3:HTTP 401"\|"3:HTTP 403"\) break;; esac$/    :/')";;
esac
case "${1:-}" in --perturb*)
  [ "$src" != "$src0" ] || { echo "  STALE PERTURBATION — ${1}: its anchor is missing in lc_emit_post, so nothing was planted and this run would FALSE-PASS"; exit 3; };;
esac
[ -n "$src" ] && printf '%s\n' "$src" | grep -q 'panel_req POST' || { echo "  FAIL could not lift lc_emit_post (or it no longer sends through panel_req)"; exit 1; }
# the stand-in panel: records the timeout it was given (its 5th argument) and the trust it was handed
panel_req(){ local m="${5:-6}"; echo "max=$m verify=$3 fp=$4" >> "$SBX/calls"
  case "$(cat "$SBX/mode")" in
    ok) return 0 ;;
    refuse) echo "connection refused"; return 1 ;;
    hang) sleep "$m"; echo "timed out"; return 1 ;;
    slow) [ "$m" -ge 5 ] && { sleep 5; return 0; }; sleep "$m"; echo "timed out"; return 1 ;;
    pin) echo "the panel presents a certificate other than the pinned one (sha256 1111…, pinned 2222…) — nothing was sent"; return 4 ;;
    reject) echo "HTTP 401"; return 3 ;;
    forbid) echo "HTTP 403"; return 3 ;;
    http500) echo "HTTP 500"; return 3 ;;
  esac; }
eval "$src"
LC_URL=https://panel.invalid:8443; LC_TOKEN=tok; LC_VERIFY=no; LC_FP="$(printf 'ab%.0s' $(seq 32))"
run(){ # <name> <mode> <state…> — the POST(s) under a hard stop, so the old loop's minutes show as a failure, not a stall
  local d="$T/$1" m="$2"; shift 2; mkdir -p "$d"; echo "$m" > "$d/mode"; : > "$d/calls"
  local s c=""; s=$(date +%s%N)
  for x in "$@"; do c="$c lc_emit_post $x;"; done
  SBX="$d" timeout 60 bash -c "$(declare -f panel_req lc_emit_post); LC_URL=$LC_URL LC_TOKEN=$LC_TOKEN LC_VERIFY=$LC_VERIFY LC_FP=$LC_FP;$c" > "$d/out" 2>&1
  echo $(( ($(date +%s%N) - s) / 1000000 )) > "$d/ms"; }
# every case runs side by side (the terminal ones take up to their full 25 s)
run hang6 hang updating & run hang25 hang updated & run refuse refuse updating & run ok ok updated &
run slow6 slow reinstalling & run slow25 slow updated & run pin pin reinstalling reinstalled-updated &
run reject reject updating & run http500 http500 updating & run reject25 reject updated & run forbid403 forbid updated & wait
ms(){ cat "$T/$1/ms"; }; n(){ grep -c . "$T/$1/calls"; }
check "[1] hang, in-progress: gave up within 6 s (+1 s slack) and said so" "$([ "$(ms hang6)" -le 7000 ] && grep -q "couldn't reach the panel" "$T/hang6/out"; echo $?)" "took $(ms hang6) ms, $(n hang6) POSTs: $(tr '\n' ' ' < "$T/hang6/calls")"
check "[2] hang, terminal: gave up within 25 s (+1 s slack)" "$([ "$(ms hang25)" -le 26000 ]; echo $?)" "took $(ms hang25) ms, $(n hang25) POSTs: $(tr '\n' ' ' < "$T/hang25/calls")"
check "[2] …and its last attempt got only the time that was left" "$([ "$(tail -1 "$T/hang25/calls" | sed 's/^max=\([0-9]*\).*/\1/')" -lt 6 ]; echo $?)" "$(tr '\n' ' ' < "$T/hang25/calls")"
check "[3] refuse: retried about once a second for the 6 s (5–7 POSTs), then gave up" "$(c=$(n refuse); [ "$c" -ge 5 ] && [ "$c" -le 7 ] && [ "$(ms refuse)" -le 7000 ]; echo $?)" "$(n refuse) POSTs in $(ms refuse) ms"
for x in slow6 slow25; do
  check "[5] slow ($x): told on the first POST, nothing printed" "$([ "$(n $x)" = 1 ] && [ ! -s "$T/$x/out" ]; echo $?)" "$(n $x) POSTs in $(ms $x) ms: $(tr '\n' ' ' < "$T/$x/calls") $(cat "$T/$x/out")"
done
check "[4] ok: one POST, no wait, nothing printed" "$([ "$(n ok)" = 1 ] && [ "$(ms ok)" -lt 1000 ] && [ ! -s "$T/ok/out" ]; echo $?)" "$(n ok) POSTs in $(ms ok) ms: $(cat "$T/ok/out")"
check "[6] pin: ONE attempt for the whole run — the refused status is not retried, the next one is not sent" "$([ "$(n pin)" = 1 ]; echo $?)" "$(n pin) POSTs: $(tr '\n' ' ' < "$T/pin/calls")"
check "[6] …and one line says why, and that the token goes nowhere else" "$([ "$(grep -c . "$T/pin/out")" = 1 ] && grep -q 'nothing was sent. The node token goes nowhere for the rest of this run' "$T/pin/out"; echo $?)" "$(cat "$T/pin/out")"
check "[7] the node's trust reaches panel_req (LC_VERIFY, LC_FP)" "$(grep -q "^max=[0-9]* verify=no fp=$LC_FP\$" "$T/ok/calls"; echo $?)" "$(cat "$T/ok/calls")"
check "[8] HTTP 401 for the whole budget → it says the panel does not accept this node's key, not \"couldn't reach\"" "$(tail -1 "$T/reject/out" | grep -q "it answered HTTP 401: it does not accept this node's key" && ! grep -q "couldn't reach" "$T/reject/out"; echo $?)" "$(cat "$T/reject/out")"
check "[8] HTTP 500 → it says what the panel answered" "$(tail -1 "$T/http500/out" | grep -q "it answered HTTP 500" && ! grep -q "couldn't reach" "$T/http500/out"; echo $?)" "$(cat "$T/http500/out")"
for x in reject reject25 forbid403; do
  check "[9] a refusal ($x): ONE attempt, no wait, no \"up to …s\" line — one line that says what it answered" "$([ "$(n $x)" = 1 ] && [ "$(ms $x)" -lt 1500 ] && ! grep -q "up to" "$T/$x/out" && [ "$(grep -c . "$T/$x/out")" = 1 ] && grep -q "it does not accept this node's key" "$T/$x/out"; echo $?)" "$(n $x) POSTs in $(ms $x) ms: $(cat "$T/$x/out")"
done
check "[9] …while HTTP 500 is still retried (a panel mid-restart may answer one)" "$([ "$(n http500)" -ge 4 ]; echo $?)" "$(n http500) POSTs"
echo; [ "$FAILS" = 0 ] && echo "GREEN — 0 failed" || echo "RED — $FAILS failed"; [ "$FAILS" = 0 ]
