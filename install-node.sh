#!/usr/bin/env bash
# install-node.sh — set up a swg-panel NODE (entry server).
#
# Installs the agent + the swg-noded daemon and points it at your panel. The node
# makes ONLY outbound HTTPS to the panel: every few seconds it posts its snapshot
# and receives its desired peer set, then reconciles locally. No inbound access,
# no SSH keys, no rsync, no queue.
#
# First add the node in the panel's "Nodes" screen — it hands you a one-time key
# and the exact command to run here, e.g.:
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh \
#     | sudo bash -s node -key SECURE_NODE_KEY -host https://panel.example.net
#
# Fill CONFIG to run unattended, or be prompted. Run as root. --dry-run renders
# files under ./dryrun and executes nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
PANEL_URL="${PANEL_URL:-}"             # https://host[:port][/subpath] of the panel   (bootstrap: -host)
NODE_TOKEN="${NODE_TOKEN:-}"           # one-time enrollment key from the Nodes screen (bootstrap: -key)
NODE_NAME="${NODE_NAME:-}"             # local label for this box's systemd unit + final message only (NOT the panel name; blank = hostname)
ENDPOINT_IP="${ENDPOINT_IP:-}"         # public IP/host clients dial for THIS node's wg
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = manage all detected)
ADOPTED_IFACES="${ADOPTED_IFACES:-}"   # interfaces migrated in by convert.sh — shown as "already on this node", not orphan/docker
WG_MTU="${WG_MTU:-1280}"               # interface MTU — 1280 leaves headroom for turn-proxy obfuscation
DNS="${DNS:-1.1.1.1}"
TLS_VERIFY="${TLS_VERIFY:-}"           # yes = verify panel's cert (real CA); no = self-signed
TLS_FINGERPRINT="${TLS_FINGERPRINT:-}" # optional: pin panel cert sha256 (hex) instead of verify
INTERVAL="${INTERVAL:-5}"              # sync period, seconds
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SRC/lib/common.sh"   # shared helpers: v_iface/v_subnet/v_hostport, next_free_port, turn_repo_owner, dl_turn_bin

# ── colours / styling (honour NO_COLOR + non-tty) ──
if { [ -t 1 ] || [ -n "${SWG_FORCE_COLOR:-}" ]; } && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_BL=$'\033[38;5;33m'; C_BROWN=$'\033[38;5;130m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; C_BL=""; C_BROWN=""; fi
b(){   printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){  printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (summary highlights)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
conf_get(){ grep -iE "^[[:space:]]*$2[[:space:]]*=" "$1" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[[:space:]]*$//'; }
# one styled interface row (green name + proto + endpoint:port + address) for the manage-loop lists, matching the SUMMARY.
iface_row(){ local n="$1" conf proto ep lp addr   # set -e safe; prefer a just-queued spec (no conf yet), else the conf
  if [ -n "${SPEC_CMD[$n]:-}" ]; then proto="${SPEC_CMD[$n]}"; lp="${SPEC_PORT[$n]:-}"; addr="${SPEC_ADDR[$n]:-}"; ep="${SPEC_EP[$n]:-}"
  else conf="${IF_CONF[$n]:-}"; proto="${IF_CMD[$n]:-?}"; ep="${IF_ENDPOINT[$n]:-${ENDPOINT_IP:-}}"
    lp="$(conf_get "$conf" ListenPort || true)"; addr="$(conf_get "$conf" Address || true)"; fi
  [ -n "$ep" ] || ep="$(detect_public_ip 2>/dev/null || true)"
  printf '    %s%s%s  %s%-10s%s  %s:%s  %s\n' "$C_GREEN" "$(printf '%-10s' "$n")" "$RESET" "$BOLD" "$(proto_label "${proto:-?}")" "$RESET" "${ep:-?}" "${lp:-?}" "${addr:-?}"; }
fwd_ifaces(){ local cp="${1##*:}" n lp out=""; for n in "${!IF_CONF[@]}"; do lp="$(conf_get "${IF_CONF[$n]}" ListenPort)"; [ -n "$lp" ] && [ "$lp" = "$cp" ] && out="${out:+$out }$n"; done; printf '%s' "$out"; }   # interface(s) a turn-proxy's ip:port forwards to (matched by ListenPort)
# add-only marker: an interface ADOPTED from outside (existing peers) carries '#swg:onboarded' in its
# conf so swg-noded never wipes its peers. The marker rides along through re-installs and conversions.
iface_onboarded(){ local c="${IF_CONF[$1]:-}"; [ -n "$c" ] && grep -q '^#swg:onboarded' "$c" 2>/dev/null; }
onboard_mark(){ local c="${IF_CONF[$1]:-}"; [ -n "$c" ] || return 0; $DRYRUN && return 0; [ -f "$c" ] || return 0
  grep -q '^#swg:onboarded' "$c" 2>/dev/null || sed -i '1i #swg:onboarded' "$c" 2>/dev/null || true; }
info(){ echo "${C_BLUE}▸${RESET} ${BOLD}$*${RESET}"; }   # ▸ light-blue, bold (universal action flag)
sub(){  echo "${C_BL}::${RESET} $*"; }                    # :: blue sub-item / progress detail
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_BROWN}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
# bring an interface up QUIETLY — wg/awg-quick spew a "[#] ip link add…" trace; swallow it on success and
# surface the captured output (indented) only on failure, so a real error still shows. bringup <tool> <iface>
bringup(){ local tool="$1" ifn="$2" out
  if $DRYRUN; then echo "    [skip] $tool up $ifn"; return 0; fi
  if out="$("$tool" up "$ifn" 2>&1)"; then return 0
  else [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/      /' >&2; return 1; fi; }
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
key(){  printf '%s[%s]%s%s'   "$C_BLUE"        "$1" "$2" "$RESET"; }   # whole label blue:        key  a 'mneziawg'           → [a]mneziawg
keyd(){ printf '%s%s[%s]%s%s' "$BOLD" "$C_BLUE" "$1" "$2" "$RESET"; }   # default label bold+blue: keyd a 'mneziawg (default)'  → [a]mneziawg (default)
STEP="${STEP_BASE:-1}"; step(){ echo; echo "$(b "Step $STEP. $1")${2:+   $2}"; STEP=$((STEP+1)); }   # sequential, continues bootstrap's numbering

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  echo; read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  echo; read -rp "  $p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

# ── input validators (0 = ok) ──
v_proto(){   case "$1" in a|awg|amneziawg|w|wg|wireguard) return 0;; *) return 1;; esac; }
v_ip(){      printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
             local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; return 0; }
v_host(){    v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_httpsurl(){ case "$1" in https://*|http://*) v_host "$(x="${1#http://}"; x="${x#https://}"; x="${x%%/*}"; printf '%s' "${x%%:*}")";; *) v_host "$(x="${1%%/*}"; printf '%s' "${x%%:*}")";; esac; }   # no scheme ok → https:// is prepended after the prompt
v_port(){    case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ local p="$1" n   # UDP port not already bound AND not already taken by an interface queued this session
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do [ "${SPEC_PORT[$n]:-}" = "$p" ] && return 1; done
  have ss || return 0; [ -z "$(ss -lnuH "sport = :$p" 2>/dev/null)" ]; }
v_freeport(){ v_port "$1" && port_free "$1"; }
# smart default ports: first install offers the base; later ones offer (highest used OF THAT KIND)+1, then the
# next host-free port. turn = TP_LISTEN units; wg/awg = highest ListenPort across confs, never below 51820+queued.
turn_default_port(){ detect_turn; local hi=0 lis p; if [ "${#TP_LISTEN[@]}" -gt 0 ]; then for lis in "${TP_LISTEN[@]}"; do p="${lis##*:}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; fi; [ "$hi" -gt 0 ] && next_free_port $((hi+1)) || next_free_port 56000; }
iface_default_port(){ local cnt="${1:-0}" hi=0 p f n base; for f in /etc/amnezia/amneziawg/*.conf /etc/wireguard/*.conf; do [ -f "$f" ] || continue; p="$(sed -n 's/^[[:space:]]*ListenPort[[:space:]]*=[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$f" | head -1)"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do p="${SPEC_PORT[$n]:-}"; case "$p" in ''|*[!0-9]*) :;; *) [ "$p" -gt "$hi" ] && hi="$p";; esac; done; base=$((51820 + cnt)); { [ "$hi" -ge 51820 ] && [ $((hi+1)) -gt "$base" ]; } && base=$((hi+1)); next_free_port "$base"; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_token(){   [ -n "$1" ] && [ "${#1}" -ge 8 ]; }   # v_iface/v_subnet/v_hostport now in lib/common.sh

# ask_choice <prompt> <default> <var> "<opt…>"  — re-prompts on bad input; ' --force' overrides
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc i
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done
    warn "ignoring invalid $var='${!var}' (expected: $opts)"; fi
  while :; do
    if read -rp "  $p [$(col "$C_BLUE" "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    case "$v" in ""|*[!0-9]*) :;; *) i=1; for o in $opts; do [ "$i" = "$v" ] && { v="$o"; break; }; i=$((i+1)); done;; esac   # [N] -> the Nth option
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; return; }; done
    [ "$forced" = yes ] && { warn "forcing unrecognised value: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts (and no interactive input to re-prompt)"
    warn "‘$v’ isn't one of: $(col "$C_BLUE" "$opts")"
    echo "  re-enter, or append $(b ' --force') to use your value anyway"
  done; }

# ask_valid <prompt> <default> <var> <validator> <hint>  — re-prompts on bad input; ' --force' overrides
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return
    warn "ignoring invalid $var='${!var}' ($hint)"; fi
  echo
  while :; do
    if read -rp "  $p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’ (got '${v:-empty}') and no interactive input to re-prompt"
    warn "$hint"
    echo "  re-enter, or append $(b ' --force') to use it anyway"
  done; }

detect_public_ip(){ # best public IPv4: default-route source, then first hostname -I
  local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  case "$ip" in 127.*) ip="";; esac                                                   # never the loopback — clients can't reach it
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -vE '^127\.' | head -n1 || true)"
  printf '%s' "$ip"; }

# ── idempotent re-install: read the current install's panel URL/token + per-interface endpoints, to
#    offer as defaults (so re-running keeps everything). Fresh install = run the uninstaller first.
EXIST_URL=""; EXIST_TOKEN=""; EXISTING=no
read_existing(){
  { [ -f /etc/swg-agent/config.json ] && have python3; } || return 0
  EXISTING=yes
  EXIST_URL="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("panel",{}).get("url",""))' 2>/dev/null || true)"
  EXIST_TOKEN="$(python3 -c 'import json;print(json.load(open("/etc/swg-agent/config.json")).get("panel",{}).get("token",""))' 2>/dev/null || true)"
  while IFS='|' read -r n ep; do [ -n "$n" ] && [ -z "${IF_ENDPOINT[$n]:-}" ] && IF_ENDPOINT[$n]="$ep"; done < <(python3 -c '
import json
for n,ic in (json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).items():
    e=ic.get("endpoint_host","")
    if e: print("%s|%s"%(n,e))' 2>/dev/null || true)
  return 0   # the while-loop falls through non-zero if the last iface's endpoint was already set; bare-called at NODE SETUP start
}
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

declare -A IF_CMD IF_CONF IF_ENDPOINT; declare -a SELECTED CREATED   # IF_ENDPOINT: per-interface public IP clients dial; CREATED: ifaces made this run
declare -A SPEC_CMD SPEC_PROTO SPEC_PORT SPEC_SUBNET SPEC_ADDR SPEC_WAN SPEC_EP SPEC_DIR; declare -a SPEC_ORDER=()   # queued interfaces (prompted now, installed at the end by apply_specs)
detect_wg(){ # scan everything under /etc/amnezia (any subdir) for awg, and /etc/wireguard for wg
  IF_CMD=(); IF_CONF=(); local f n
  if [ -d /etc/amnezia ]; then
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  fi
  for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
}
ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools if missing (idempotent, non-fatal -> 0/1)
  local cmd="$1"
  have "$cmd" && return 0
  info "installing $([ "$cmd" = wg ] && echo 'WireGuard' || echo 'AmneziaWG') tools via apt — this can take a minute…"
  if [ "$cmd" = wg ]; then run apt-get update -qq || true; run apt-get install -y wireguard || true
  else run apt-get update -qq || true; run apt-get install -y software-properties-common || true
       run add-apt-repository -y ppa:amnezia/ppa || true; run apt-get update -qq || true; run apt-get install -y amneziawg || true; fi
  $DRYRUN && return 0
  have "$cmd"
}
awg_obfuscation(){ # AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))
  b1=$(( 5 + (RANDOM*RANDOM) % 900000000 ));          b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 )); b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  printf 'I1 = <b 0xc300000001><r 1200>\n'   # QUIC v1 Initial prefix + random; no <c>/<t> (Android-safe)
}
server_addr(){ have python3 || die "python3 required for the tunnel address (also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
# pick a default tunnel subnet that isn't already taken — by a queued spec OR a persisted interface — so a
# 2nd interface doesn't collide with a non-default subnet the user chose for the 1st (and v_subnet_free rejects a typed dup).
_net24(){ local ip="${1%%/*}" m="${1##*/}"; [ "$1" = "$m" ] && m=24; printf '%s.0/%s' "${ip%.*}" "$m"; }   # 10.9.0.1/24 → 10.9.0.0/24
subnet_used(){ local s n a; s="$(_net24 "$1")"
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do [ -n "${SPEC_SUBNET[$n]:-}" ] && [ "$(_net24 "${SPEC_SUBNET[$n]}")" = "$s" ] && return 0; done
  for n in "${!IF_CONF[@]}"; do a="$(sed -n 's/^[[:space:]]*Address[[:space:]]*=[[:space:]]*\([0-9./]*\).*/\1/p' "${IF_CONF[$n]}" 2>/dev/null | head -1)"; [ -n "$a" ] && [ "$(_net24 "$a")" = "$s" ] && return 0; done
  return 1; }
# default subnet = (highest used 10.X.0.0/24 second-octet)+1, then the next free above it (10.8 if none).
next_free_subnet(){ local hi=7 n a o
  for n in ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do a="${SPEC_SUBNET[$n]:-}"; [ -n "$a" ] || continue; o="$(_net24 "$a" | cut -d. -f2)"; case "$o" in ''|*[!0-9]*) :;; *) [ "$o" -gt "$hi" ] && hi="$o";; esac; done
  for n in "${!IF_CONF[@]}"; do a="$(conf_get "${IF_CONF[$n]}" Address)"; [ -n "$a" ] || continue; o="$(_net24 "$a" | cut -d. -f2)"; case "$o" in ''|*[!0-9]*) :;; *) [ "$o" -gt "$hi" ] && hi="$o";; esac; done
  o=$((hi+1)); while [ "$o" -lt 255 ] && subnet_used "10.$o.0.0/24"; do o=$((o+1)); done; echo "10.$o.0.0/24"; }
v_subnet_free(){ v_subnet "$1" || return 1; subnet_used "$1" && return 1; return 0; }
# default interface index = (highest numeric suffix across existing + queued names)+1 (awg3,wg4 → 5).
iface_next_index(){ local hi=-1 n s; for n in "${!IF_CMD[@]}" ${SPEC_ORDER[@]+"${SPEC_ORDER[@]}"}; do s="${n##*[!0-9]}"; case "$s" in ''|*[!0-9]*) :;; *) [ "$s" -gt "$hi" ] && hi="$s";; esac; done; echo $((hi+1)); }
# warn if any two managed interfaces share a tunnel subnet — only ONE can be up at a time (the rest fail to
# start), so the node will report some interfaces down until the operator edits one to a free subnet.
warn_dup_subnets(){ local n a key; declare -A _seen=()
  for n in "${!IF_CONF[@]}"; do a="$(conf_get "${IF_CONF[$n]}" Address)"; [ -n "$a" ] || continue; key="$(_net24 "$a")"
    if [ -n "${_seen[$key]:-}" ]; then warn "interfaces $(col "$C_GREEN" "$n") and $(col "$C_GREEN" "${_seen[$key]}") share subnet $(b "$key") — only one can be up at a time; edit one to a free subnet, then restart it."
    else _seen[$key]="$n"; fi
  done; }
# Two-phase interface creation: spec_iface() only PROMPTS and queues a spec, so the user can add
# every interface up front; apply_specs() then installs tools + writes confs + brings them all up
# once, at the end. Queued names show in 'mine' (via CREATED) and block name collisions immediately.
spec_iface(){ # prompt for one interface and queue it (no install yet)
  local _proto proto name port subnet addr cmd dir wan ep idx defname defport defsub
  detect_wg   # refresh IF_CMD/IF_CONF from disk first, so the name/port/subnet defaults always see every existing interface
  idx=$(( ${#IF_CMD[@]} + ${#SPEC_ORDER[@]} ))   # offset defaults past existing + already-queued ifaces
  menu "$(col "$C_BLUE" '[1]') $(keyd a 'mneziawg (default)')" "WireGuard with AmneziaWG obfuscation. Runs on the host's AmneziaWG kernel module."
  menu "$(col "$C_BLUE" '[2]') $(key w 'ireguard')"            "Plain WireGuard — no obfuscation, lowest overhead. Runs on the host's WireGuard kernel module."
  ask_choice "Select the protocol you want to create (number, letter or name)" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) proto=wg; cmd=wg;  dir=/etc/wireguard;;
                                 *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  local nidx; nidx=$(iface_next_index)   # name = highest-suffix+1, bumped past any exact collision
  defname="$([ "$cmd" = awg ] && echo "awg$nidx" || echo "wg$nidx")"
  while [ -n "${IF_CMD[$defname]:-}" ] || [ -n "${SPEC_CMD[$defname]:-}" ] || [ -e "/etc/amnezia/amneziawg/$defname.conf" ] || [ -e "/etc/wireguard/$defname.conf" ]; do
    nidx=$((nidx+1)); defname="$([ "$cmd" = awg ] && echo "awg$nidx" || echo "wg$nidx")"; done
  while :; do
    ask_valid "Interface name" "$defname" name v_iface "1–15 chars: letters, digits, - or _"
    if [ -n "${IF_CMD[$name]:-}" ] || [ -n "${SPEC_CMD[$name]:-}" ] || [ -e "/etc/amnezia/amneziawg/$name.conf" ] || [ -e "/etc/wireguard/$name.conf" ]; then
      warn "interface '$name' already exists — pick another name"; name=""; continue
    fi
    break
  done
  defport=$(iface_default_port "$idx"); defsub="$(next_free_subnet)"
  ask_valid "Listen port" "$defport" port v_freeport "port 1–65535 and free (not already in use)"
  ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$defsub" subnet v_subnet_free "a CIDR not already used, e.g. 10.8.0.0/24"
  addr="$(server_addr "$subnet")"
  echo "    server address $(col "$C_GREEN" "$addr") — peers get the rest of $subnet"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0             # auto WAN egress NIC — clients NAT out this (change it later in the panel)
  echo "    Used $(bb "$wan") egress interface for $(col "$C_GREEN" "$name")"
  ep="$(detect_public_ip)"                                   # auto endpoint clients dial — public IP/host (change it later in the panel)
  echo "    Used $(bb "$ep") endpoint IP for $(col "$C_GREEN" "$name")"
  SPEC_CMD[$name]="$cmd"; SPEC_PROTO[$name]="$proto"; SPEC_PORT[$name]="$port"; SPEC_SUBNET[$name]="$subnet"
  SPEC_ADDR[$name]="$addr"; SPEC_WAN[$name]="$wan"; SPEC_EP[$name]="$ep"; SPEC_DIR[$name]="$dir"
  SPEC_ORDER+=("$name"); CREATED+=("$name")                  # CREATED makes it show in 'mine' on the next pass
  ok "queued interface $(col "$C_GREEN" "$name") ($proto, :$port) — installed once you finish adding interfaces"
}
apply_specs(){ # install tools + write confs + bring up every queued interface, then prune failures
  [ "${#SPEC_ORDER[@]}" -gt 0 ] || return 0
  local name proto port subnet addr conf cmd priv dir wan up down upok ep failed=""
  echo; info "Setting up ${#SPEC_ORDER[@]} interface(s)…"
  for name in "${SPEC_ORDER[@]}"; do
    cmd="${SPEC_CMD[$name]}"; proto="${SPEC_PROTO[$name]}"; port="${SPEC_PORT[$name]}"; subnet="${SPEC_SUBNET[$name]}"
    addr="${SPEC_ADDR[$name]}"; wan="${SPEC_WAN[$name]}"; ep="${SPEC_EP[$name]}"; dir="${SPEC_DIR[$name]}"; conf="$dir/$name.conf"
    if ! ensure_wg_tools "$cmd"; then warn "couldn't install $cmd tools — skipping interface '$name'"; failed="$failed $name"; continue; fi
    up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
    printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
    run sysctl -q -w net.ipv4.ip_forward=1
    if $DRYRUN; then priv="<generated-on-real-run>"
    elif ! priv="$("$cmd" genkey 2>/dev/null)" || [ -z "$priv" ]; then warn "'$cmd genkey' failed — skipping interface '$name'"; failed="$failed $name"; continue; fi
    { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\nMTU = %s\n' "$priv" "$addr" "$port" "$WG_MTU"
      printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
      if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
    # bring up — NON-FATAL: a port/subnet clash must not abort the whole install (set -e)
    upok=yes
    if [ "$cmd" = awg ]; then bringup awg-quick "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable --quiet "awg-quick@$name" || true; }
    else                     bringup wg-quick  "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable --quiet "wg-quick@$name"  || true; }; fi
    if [ "$upok" = no ]; then
      warn "couldn't bring up '$name' (a port or subnet may already be in use) — removing its conf; try again with different values"
      run rm -f "$conf"; failed="$failed $name"; continue
    fi
    IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; IF_ENDPOINT[$name]="$ep"; LAST_IFACE="$name"
    ok "created $proto interface $(col "$C_GREEN" "$name") on :$port (server $addr, NAT out $wan)"
  done
  if [ -n "$failed" ]; then   # drop interfaces that failed to come up from the selected set
    local keep=() n; for n in ${SELECTED[@]+"${SELECTED[@]}"}; do _in "$n" "$failed" || keep+=("$n"); done; SELECTED=(${keep[@]+"${keep[@]}"})
  fi
}
# ── interface picker helpers (bare-metal) ──
node_ifaces(){ # interfaces this node already manages (keys in its config.json) — the "already on this node" set
  { [ -f /etc/swg-agent/config.json ] && have python3; } || return 0
  python3 -c 'import json;print("\n".join((json.load(open("/etc/swg-agent/config.json")).get("interfaces") or {}).keys()))' 2>/dev/null || true
}
_in(){ case " $2 " in *" $1 "*) return 0;; *) return 1;; esac; }
docker_node_ifaces(){   # interfaces managed by a co-located DOCKER node (its ./data/node-confs)
  local d c; for d in "${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"; do
    [ -d "$d/data/node-confs" ] || continue
    for c in "$d"/data/node-confs/*.conf; do [ -f "$c" ] && basename "$c" .conf; done
  done
}
transfer_from_docker(){ # import a docker node-conf to bare-metal: copy out, ADD host NAT, drop the source
  local n="$1" d="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}" src dest addr subnet wan up down
  src="$d/data/node-confs/$n.conf"; [ -f "$src" ] || return 0
  if grep -qiE '^[[:space:]]*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4|I1)[[:space:]]*=' "$src"; then dest="/etc/amnezia/amneziawg/$n.conf"; else dest="/etc/wireguard/$n.conf"; fi
  run mkdir -p "$(dirname "$dest")"
  # docker confs carry NO PostUp (the container does its own NAT) — inject host NAT so the bare iface routes
  addr="$(sed -n 's/^[[:space:]]*[Aa]ddress[[:space:]]*=//p' "$src" | head -1 | sed 's/,.*//; s/[[:space:]]//g')"
  subnet="$(python3 -c 'import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))' "$addr" 2>/dev/null || echo "$addr")"
  wan="$(detect_wan)"; [ -n "$wan" ] || wan=eth0
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  if $DRYRUN; then echo "    [skip] import $src → $dest (+ host NAT)"
  else awk -v up="$up" -v down="$down" '
    /^[[:space:]]*[Pp]ost(Up|Down)[[:space:]]*=/ {next}
    {print}
    /^\[Interface\][[:space:]]*$/ && !d {print "PostUp = " up; print "PostDown = " down; d=1}
  ' "$src" > "$dest"; chmod 600 "$dest"; fi
  run rm -f "$src"
  ok "imported $(col "$C_GREEN" "$n") from the docker node-confs (host NAT added)"
}
choose_ifaces(){ # let the user pick which detected interfaces to manage; 'new' creates more
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    info "Checking for wg / awg on this host…"
    # only nothing-to-do if there are NEITHER /etc confs NOR leftover docker node-confs (a removed
    # docker node whose peers were kept) — the latter are offered for import in the loop below.
    if [ "${#IF_CMD[@]}" -eq 0 ] && [ -z "$(docker_node_ifaces)" ]; then
      warn "No wg / awg interfaces found in /etc/wireguard or /etc/amnezia."
      local doit; ask_yn "Create one now? (installs WireGuard / AmneziaWG only if missing)" y doit
      [ "$doit" = yes ] && spec_iface
      detect_wg
      [ "${#IF_CMD[@]}" -eq 0 ] && [ "${#SPEC_ORDER[@]}" -eq 0 ] && { $DRYRUN || die "create an interface, then re-run"; IF_CMD[awg0]=awg; IF_CONF[awg0]=/etc/amnezia/amneziawg/awg0.conf; }
    elif [ "${#IF_CMD[@]}" -eq 0 ]; then
      info "Found leftover docker node-confs to import: $(col "$C_GREEN" "$(echo $(docker_node_ifaces))")"
    fi
    local names pick n dk avail mine xfer bad yn; local -a sel=()
    while :; do
      detect_wg; names="${!IF_CMD[*]}"
      dk=""; for n in $(docker_node_ifaces); do _in "$n" "${ADOPTED_IFACES:-}" || dk="$dk $n"; done; dk="$(echo $dk)"   # the iface(s) we're converting away from docker are ours now, not "docker" ones
      mine=""; for n in $(node_ifaces) ${ADOPTED_IFACES:-} ${CREATED[@]+"${CREATED[@]}"}; do _in "$n" "$mine" || mine="$mine $n"; done; mine="$(echo $mine)"
      avail=""; for n in $names; do _in "$n" "$mine" && continue; _in "$n" "$dk" && continue; avail="$avail $n"; done; avail="$(echo $avail)"
      echo
      [ -n "$mine" ] && { echo "  Interfaces already on this node:"; echo; for n in $mine; do iface_row "$n"; done; echo; }
      if [ -n "$avail" ]; then echo "  Available orphan interfaces:"; echo; for n in $avail; do iface_row "$n"; done; echo
      else echo "  Available orphan interfaces: (none)"; fi
      [ -n "$dk" ] && { printf "  Interfaces from a docker node on this server (import to this node):"; for n in $dk; do printf ' %s' "$(col "$C_RED" "$n")"; done; echo; }
      warn_dup_subnets   # flag any interfaces that share a subnet (only one of them can be up)
      echo
      if [ -z "$avail" ] && [ -z "$mine" ] && [ -n "$dk" ]; then   # only docker-node interfaces → transfer or create
        printf "  Enter a name to %s it from the docker node, or %s to create one: " "$(col "$C_BLUE" transfer)" "$(col "$C_BLUE" new)"
      elif [ -n "$avail" ]; then                                   # orphans present → manage all / some / none
        echo "  Press $(b Enter) to manage $(col "$C_BLUE" 'all orphans above') and continue"
        echo "  Enter interface $(b names) (space-separated) to manage or migrate specific ones"
        [ -n "$mine" ] && echo "  Enter $(col "$C_BLUE" done) to keep only this node's interfaces (leave the orphans)"
        printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
      else                                                        # no orphans → finish or add more
        echo "  Press $(b Enter) to finish with this node's interfaces"
        [ -n "$dk" ] && echo "  Enter interface $(b names) to migrate one from the docker node"
        printf "  Enter %s to create another interface: " "$(col "$C_BLUE" '[n]ew')"
      fi
      if ! read -r pick 2>/dev/null </dev/tty; then echo; warn "no interactive input — keeping this node's interfaces"; sel=($mine $avail); break; fi
      pick="$(echo $pick)"
      if [ -z "$pick" ]; then                                     # Enter → keep mine + onboard all orphans
        sel=($mine $avail)
        [ ${#sel[@]} -gt 0 ] || { warn "nothing to manage — type 'new' to create an interface"; continue; }
        break
      fi
      if [ "$pick" = done ]; then                                 # keep only this node's interfaces (leave orphans)
        [ -n "$mine" ] || { warn "this node has no interfaces yet — manage one or type 'new'"; continue; }
        sel=($mine); break
      fi
      { [ "$pick" = new ] || [ "$pick" = n ]; } && { spec_iface; continue; }
      xfer=""; bad=""
      for n in $pick; do _in "$n" "$mine" && continue; _in "$n" "$avail" && continue; _in "$n" "$dk" && { xfer="$xfer $n"; continue; }; bad="$bad $n"; done
      [ -n "$bad" ] && { warn "not found:$bad — pick from the lists, or 'new'"; continue; }
      if [ -n "$xfer" ]; then
        printf "  Are you sure you want to transfer %s to this node? (y/N): " "$(col "$C_RED" "$(echo $xfer)")"
        read -r yn 2>/dev/null </dev/tty || yn=n
        case "$yn" in [Yy]*) for n in $xfer; do transfer_from_docker "$n" || true; done; detect_wg;; *) continue;; esac
      fi
      sel=($mine); for n in $pick; do _in "$n" "$mine" || sel+=("$n"); done; break   # keep mine + the chosen ones
    done
    # an interface we just ADOPTED (an orphan we didn't create, not arriving via a conversion import)
    # is add-only — tag its conf so swg-noded keeps its existing peers instead of wiping them.
    _nodeifs="$(node_ifaces | tr '\n' ' ')"
    for n in ${sel[@]+"${sel[@]}"}; do n="${n// /}"; [ -z "$n" ] && continue
      _in "$n" "$_nodeifs" && continue                       # already managed before → keep its current marker
      _in "$n" "${CREATED[*]:-}" && continue                 # we created it this run → authoritative
      _in "$n" "${ADOPTED_IFACES:-}" && continue             # conversion import → its conf already carries the right marker
      onboard_mark "$n"
    done
    SELECTED=("${sel[@]}")
  fi
  # CONVERT docker→bare: the docker node stayed UP through every prompt above. NOW — right before the bare
  # interfaces come up — do the ATOMIC SWITCH: stop the docker datapath (frees the wg ports) + clear any host
  # netdevs it left behind, so wg-quick can bind. The conf/key COPY already happened (convert.sh), so this is
  # the only destructive step, and it's at the very end.
  if [ "${SWG_CONVERT:-}" = 1 ] && ! $DRYRUN && command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx swg-node; then
    info "Switching over — stopping the docker node, then bringing the interfaces up bare-metal…"
    lc_teardown_docker "${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
    for _n in ${SELECTED[@]+"${SELECTED[@]}"}; do _n="${_n// /}"; [ -n "$_n" ] && command -v ip >/dev/null 2>&1 && ip link show "$_n" >/dev/null 2>&1 && ip link delete dev "$_n" 2>/dev/null || true; done
  fi
  apply_specs   # install tools + write confs + bring up every queued interface now (after all prompts)
  detect_wg
  local _ep
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }
    [ -n "${IF_ENDPOINT[$n]:-}" ] && continue   # interfaces just created already have an endpoint
    _ep="$(detect_public_ip)"; IF_ENDPOINT[$n]="$_ep"   # auto endpoint clients dial (change it later in the panel)
    echo "    Used $(bb "$_ep") endpoint IP for $(col "$C_GREEN" "$n")"; done
  [ "${#SELECTED[@]}" -gt 0 ] && echo
  # bring up any adopted interface whose conf is here but isn't running yet (transfer-from-docker / conversion)
  info "Bringing up the node's interfaces (starting each one — this can take a moment for many)…"
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
    ip link show "$n" >/dev/null 2>&1 && continue          # already up → leave it
    _c="${IF_CMD[$n]:-awg}"; ensure_wg_tools "$_c" || continue
    if [ "$_c" = awg ]; then bringup awg-quick "$n" && { run systemctl enable --quiet "awg-quick@$n" || true; } || warn "couldn't bring up adopted '$n' — check $(b "${IF_CONF[$n]:-}")"
    else                     bringup wg-quick  "$n" && { run systemctl enable --quiet "wg-quick@$n"  || true; } || warn "couldn't bring up adopted '$n' — check $(b "${IF_CONF[$n]:-}")"; fi
  done
  [ "${#SELECTED[@]}" -gt 0 ] || die "no interfaces selected"
  ok "Managing: $(b "$(col "$C_GREEN" "${SELECTED[*]}")")"
}

# ───────────────────────── turn-proxy (vk-turn-proxy) ─────────────────────────
# Tunnels WireGuard/AmneziaWG through VK/Yandex TURN servers. Config is the systemd
# unit's CLI args: -listen <pub-ip:port>  -connect <wg-ip:port>. We detect any such
# unit, can install the binary from a fork's GitHub releases, and record listen→connect
# so the panel can later tell a turn-proxied client from a direct one.
# https://github.com/cacggghp/vk-turn-proxy
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
TURN_RECORD="${TURN_RECORD:-/etc/swg-agent/turn-proxy.json}"
declare -A TP_LISTEN TP_CONNECT TP_WRAP
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }   # 32-byte key as 64 hex chars
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Per-fork obfuscation flags (verified from each binary's -h). Echoes the flags WITH a
# freshly generated -wrap-key baked in (kiper292 has no wrap support → empty).
turn_wrap_flags(){ local k; case "$1" in
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  WINGS-N)      k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  Moroka8)      k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;   # verified from its README: -wrap -wrap-key
  *) printf '';; esac; }
turn_wg_ports(){   # echo "<iface>:<ListenPort>" for every interface managed in the wg/awg step
  local n p
  for n in ${SELECTED[@]+"${SELECTED[@]}"}; do
    [ -n "${IF_CONF[$n]:-}" ] || continue
    p="$(grep -iE '^[[:space:]]*ListenPort[[:space:]]*=' "${IF_CONF[$n]}" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[^0-9].*//')"
    [ -n "$p" ] && printf '%s:%s\n' "$n" "$p"
  done
  return 0   # a final iface with no ListenPort would otherwise leave the loop non-zero → trips set -e at ports="$(turn_wg_ports)"
}
detect_turn(){   # any systemd unit whose ExecStart carries both -listen and -connect is a turn-proxy
  TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local u name exe lis con wk envf params
  for u in /etc/systemd/system/*.service; do
    [ -e "$u" ] || continue
    exe="$(sed -n 's/^ExecStart=//p' "$u" 2>/dev/null | head -1)"
    case "$exe" in *-listen*-connect*|*-connect*-listen*) ;; *) continue;; esac
    name="$(basename "$u" .service)"
    case "$exe" in
      *'${SWG_'*)   # EnvironmentFile form — read listen/connect/params out of turn.env
        envf="$(sed -n 's/^EnvironmentFile=-\{0,1\}//p' "$u" 2>/dev/null | head -1)"
        lis="$(sed -n 's/^SWG_LISTEN=//p' "$envf" 2>/dev/null | head -1)"
        con="$(sed -n 's/^SWG_CONNECT=//p' "$envf" 2>/dev/null | head -1)"
        params="$(sed -n 's/^SWG_PARAMS=//p' "$envf" 2>/dev/null | head -1)"
        wk="$(printf '%s\n' "$params" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
      *)            # legacy baked-ExecStart form
        lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
        con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
        wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')" ;;
    esac
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"
  done
}
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }   # turn_latest_tag <owner/repo>
  curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ # <fork> <owner/repo> <listen ip:port> <connect ip:port> <extra-flags>
  local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver port inst fdir sbin
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  # key each instance by <fork>-<port> so one fork can run many times (different ports + wrap keys)
  port="${listen##*:}"; inst="$fork-$port"; svc="vk-turn-proxy-$inst"
  fdir="$TURN_DIR/.bin/$fork"; sbin="$fdir/server"   # ONE binary per fork — shared by every instance
  dir="$TURN_DIR/$inst"; bin="$dir/server"            # this instance: turn.env + a 'server' symlink → the shared binary
  if [ -e "/etc/systemd/system/$svc.service" ]; then warn "turn-proxy $svc already exists — pick another port"; return 0; fi
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$fdir" "$PREFIX$dir"
  if $DRYRUN; then echo "    [skip] reuse-or-download the $fork binary → $sbin"
  elif [ -x "$PREFIX$sbin" ]; then info "reusing the $fork binary already downloaded ($sbin)"
  else
    info "Installing $owner ($listen → $connect) — downloading the binary from GitHub (up to ~2 min)…"
    if ! { dl_turn_bin "$owner" "$arch" "$PREFIX$sbin" && chmod +x "$PREFIX$sbin"; }; then
      warn "download failed for $owner — skipping this turn-proxy (retry later, or set SWG_TURN_MIRROR=<proxy> and re-run)"; return 0
    fi
  fi
  $DRYRUN || ln -sfn "../.bin/$fork/server" "$PREFIX$bin"   # ExecStart points here; resolves to the shared binary
  ver="$(turn_latest_tag "$owner")"
  printf '%s\n' "$owner"          | writef "$fdir/repo.txt" 644
  printf '%s\n' "${ver:-unknown}" | writef "$fdir/version.txt" 644
  # listen/connect/params live in turn.env so a panel edit only rewrites it + restarts (no daemon-reload)
  writef "$dir/turn.env" 600 <<EOF
SWG_LISTEN=${listen}
SWG_CONNECT=${connect}
SWG_PARAMS=${extra}
EOF
  writef "/etc/systemd/system/$svc.service" 600 <<EOF
[Unit]
Description=vk-turn-proxy ($owner) — ${listen} → ${connect}
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=-${dir}/turn.env
ExecStart=${bin} -listen \${SWG_LISTEN} -connect \${SWG_CONNECT} \$SWG_PARAMS
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload; run systemctl enable --quiet --now "$svc" || warn "couldn't start $svc"
  ok "installed turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect"
}
# turn-proxy forward-to value: accept an interface NAME (resolved to 127.0.0.1:<its listen port>) or a custom ip:port.
v_fwd(){ local names; names=" $(turn_wg_ports | cut -d: -f1 | tr '\n' ' ')"; case "$names" in *" $1 "*) return 0;; esac; v_hostport "$1"; }
fwd_resolve(){ local n p; while IFS=: read -r n p; do [ -n "$n" ] && [ "$n" = "$1" ] && { echo "127.0.0.1:$p"; return; }; done <<< "$(turn_wg_ports)"; echo "$1"; }
install_turn_proxy(){   # <fork> — params, then install (the fork is chosen in choose_turn_proxy)
  local sel="$1" owner pub port connect; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "$(detect_public_ip)" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "$(turn_default_port)" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local _n; for _n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$_n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$_n' — pick another port (enter 'new' again)"; return 0; }; done
  local ports defport=51820 defname="127.0.0.1:51820" n p proto label clabel pad; ports="$(turn_wg_ports)"
  echo
  if [ -n "$ports" ]; then
    defname="$(printf '%s\n' "$ports" | head -1 | cut -d: -f1)"   # first interface NAME
    echo "  Available wg/awg interfaces:"
    while IFS=: read -r n p; do proto="${IF_CMD[$n]:-wg}"
      label="[$n] on $proto"; clabel="$(col "$C_GREEN" "[$n]") on $(b "$proto")"
      pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
      printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$p")"
    done <<< "$ports"
  fi
  ask_valid "WireGuard/AmneziaWG address it forwards to - interface name or custom ip:port" "$defname" connect v_fwd "an interface name (e.g. awg0) or ip:port"
  connect="$(fwd_resolve "$connect")"
  echo
  local wrap; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap"
}
write_turn_record(){   # record detected turn-proxies for the panel (Phase 2: direct-vs-turn + wrap key for client configs)
  detect_turn; local json="" sep="" n
  for n in "${!TP_LISTEN[@]}"; do
    json+="$sep    { \"service\": \"$n\", \"listen\": \"${TP_LISTEN[$n]}\", \"connect\": \"${TP_CONNECT[$n]}\", \"wrap_key\": \"${TP_WRAP[$n]}\" }"; sep=$',\n'
  done
  writef "$TURN_RECORD" 640 <<EOF
{
  "turn_proxies": [
$json
  ]
}
EOF
}
choose_turn_proxy(){   # one looped step: list installed (if any) + available branches; a branch installs, Enter proceeds
  info "Checking for turn-proxy servers on this host…"
  local sel names n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    echo
    if [ "${#names[@]}" -gt 0 ]; then
      echo "  Installed turn-proxy servers:"; echo
      for n in "${names[@]}"; do _fw="$(fwd_ifaces "${TP_CONNECT[$n]}")"; printf '    %s%s%s %s → %s%s\n' "$C_GREEN" "$n" "$RESET" "${TP_LISTEN[$n]}" "${TP_CONNECT[$n]}" "${_fw:+ $(col "$C_GREEN" "($_fw)")}"; done
    else
      warn "No turn-proxy servers found on this box."
    fi
    echo
    echo "  Here is a list of turn-proxy branches available for installation:"
    echo
    menu "$(col "$C_BLUE" '[0] [c]acggghp')"     "The original project - https://github.com/cacggghp/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[1] [W]INGS-N')"      "Fork by WINGS-N - https://github.com/WINGS-N/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[2] [s]amosvalishe')" "Fork by samosvalishe - https://github.com/samosvalishe/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[3] [k]iper292')"     "Fork by kiper292 - https://github.com/kiper292/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[4] [M]oroka8')"      "Fork by Moroka8 - https://github.com/Moroka8/vk-turn-proxy"
    menu "$(col "$C_BLUE" '[5] [a]nton48')"      "Fork by anton48 - https://github.com/anton48/vk-turn-proxy"
    printf '  Enter a number, letter or name to install, or just press %s to skip and proceed with the setup: ' "$(b Enter)"
    if ! read -r sel 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    sel="${sel//[[:space:]]/}"
    [ -z "$sel" ] && break
    sel="$(printf '%s' "$sel" | tr '[:upper:]' '[:lower:]')"   # case-insensitive (W/w, M/m, …)
    case "$sel" in
      0|c|cacggghp|original|main)  install_turn_proxy cacggghp; continue;;
      1|w|wings|wings-n)           install_turn_proxy WINGS-N; continue;;
      2|s|samosvalishe)            install_turn_proxy samosvalishe; continue;;
      3|k|kiper|kiper292)          install_turn_proxy kiper292; continue;;
      4|m|moroka|moroka8)          install_turn_proxy Moroka8; continue;;
      5|a|anton|anton48)           install_turn_proxy anton48; continue;;
      *) warn "enter 0–5, a letter (c/w/s/k/m/a) or a name (or press Enter to skip)";;
    esac
  done
  write_turn_record
}

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# convert.sh (docker→bare) re-enters here AFTER migrating the existing turn-proxies, to offer the same
# "add more?" step interfaces get — reusing this script's turn menu instead of duplicating the fork list
# in convert.sh. choose_turn_proxy lists what's already installed (incl. the just-migrated units), lets
# you add more, and (re)writes the turn record; restart swg-noded so any additions reach the panel.
if [ "${SWG_TURN_ADD:-}" = 1 ]; then
  echo; info "TURN-PROXY setup — add more, or press $(b Enter) to keep the migrated ones."
  echo
  # choose_ifaces didn't run in this turn-only re-entry, so seed SELECTED from the node's on-disk
  # interfaces — otherwise turn_wg_ports is empty and the "forwards to" prompt can't suggest an interface.
  detect_wg; SELECTED=("${!IF_CMD[@]}")
  choose_turn_proxy
  run systemctl restart swg-noded || warn "couldn't restart swg-noded — added turn-proxies reach the panel on its next start"
  exit 0
fi

# ═══════════════ NODE SETUP ═══════════════
echo; info "BARE-METAL SWG NODE SETUP"
read_existing
if [ "$EXISTING" = yes ]; then
  info "Existing node install detected — keeping your interfaces + data. Press $(b Enter) to keep each value (to start fresh, run the uninstaller first)."
fi

# RE-INSTALL: signal "re-installing" the MOMENT the script starts (before any prompt), using the stored panel
# URL/token, and drop the keypair backups so swg-noded re-harvests. lc_init's traps emit the terminal on exit;
# a re-install always installs the latest → "re-installed and updated". (convert.sh owns the signal mid-convert.)
if [ "$EXISTING" = yes ] && ! $DRYRUN && [ "${SWG_CONVERT:-}" != 1 ] && [ -n "$EXIST_URL" ] && [ -n "$EXIST_TOKEN" ]; then
  rm -rf /var/lib/swg-noded/iface-keys 2>/dev/null || true
  LC_URL="$EXIST_URL"; LC_TOKEN="$EXIST_TOKEN"
  LC_VERIFY="$(python3 -c 'import json;print("yes" if (json.load(open("/etc/swg-agent/config.json")).get("panel") or {}).get("verify",True) else "no")' 2>/dev/null || echo no)"
  lc_init reinstall lc_emit_post
  LC_SUCCESS="reinstalled-updated"
fi

# Panel connection — normally supplied by the install command's -host / -key flags; on a re-install
# the current values are offered as defaults so you can just press Enter.
if $DRYRUN; then ask "Panel URL (https://host[/subpath])" "$EXIST_URL" PANEL_URL
else ask_valid "Panel URL (https://host[/subpath])" "$EXIST_URL" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"; fi
# token: a re-install reuses the existing one SILENTLY (no prompt — re-typing it is useless/error-prone);
# a fresh install (or no stored token) still asks. -key always wins.
if [ -n "$NODE_TOKEN" ]; then :                                                # provided via -key
elif [ "$EXISTING" = yes ] && [ -n "$EXIST_TOKEN" ]; then NODE_TOKEN="$EXIST_TOKEN"
elif $DRYRUN; then ask "Node enrollment key (from the Nodes screen)" "$EXIST_TOKEN" NODE_TOKEN
else ask_valid "Node enrollment key (from the Nodes screen)" "$EXIST_TOKEN" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"; fi
case "$PANEL_URL" in https://*) ;; http://*) warn "panel URL is http:// — the key would travel in clear. Continue only if you know why.";; *) PANEL_URL="https://$PANEL_URL";; esac   # no scheme → default https://
# if the operator re-pointed the node at a different panel, the lc terminal should reach the NEW one
[ "$EXISTING" = yes ] && [ -n "${LC_TOKEN:-}" ] && [ -n "$PANEL_URL" ] && LC_URL="$PANEL_URL"

if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ]; then
  ask_yn "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" n TLS_VERIFY
fi

NODE_NAME="${NODE_NAME:-$(hostname -s 2>/dev/null || hostname)}"   # local label (systemd unit + final message)
# Box name on the panel: on a re-install, offer to change it (default = the name the panel currently has for
# this token). A fresh install's name comes from Nodes → Add node. PUSH_NAME != "" means push the change.
PUSH_NAME=""
if [ "$EXISTING" = yes ] && [ -n "$NODE_TOKEN" ] && [ -n "$PANEL_URL" ] && ! $DRYRUN; then
  _ins=""; [ "${TLS_VERIFY:-no}" = yes ] || _ins="-k"
  _cur="$(curl -fsS $_ins --max-time 8 -H "Authorization: Bearer $NODE_TOKEN" "${PANEL_URL%/}/api/node/whoami" 2>/dev/null | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("name") or "")' 2>/dev/null || true)"
  step "Box name on the panel"
  ask_valid "Node name (shown in the panel)" "${_cur:-$NODE_NAME}" PUSH_NAME v_name "1–40 chars: letters, digits, - or _"
  [ -n "$_cur" ] && [ "$PUSH_NAME" = "$_cur" ] && PUSH_NAME=""    # unchanged → nothing to push
fi

# push a box-name change (if the operator entered a new one above)
if [ "$EXISTING" = yes ] && ! $DRYRUN && [ -n "$PUSH_NAME" ]; then
  curl -fsS ${_ins:-} --max-time 8 -X POST -H "Authorization: Bearer $NODE_TOKEN" -H "Content-Type: application/json" \
    --data "$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$PUSH_NAME")" "${PANEL_URL%/}/api/node/rename" >/dev/null 2>&1 || true
fi

step "WireGuard / AmneziaWG setup" "(each interface has its own endpoint IP)"
echo
choose_ifaces

# a docker→bare conversion already migrated the existing turn-proxies (convert.sh) — don't offer the fork menu,
# but STILL record the migrated units (write_turn_record), or the panel would show no turn-proxies after the convert.
if [ "${SWG_CONVERT:-}" = 1 ]; then
  write_turn_record
else
  step "TURN-PROXY setup"
  echo
  choose_turn_proxy
fi

# ───────────────────────── install binaries ─────────────────────────
info "Agent + daemon"
for f in swg-agent swg-noded; do [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"; done
mkdir -p "$PREFIX$AGENT_DIR" "$PREFIX$NODED_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"
chmod 755 "$PREFIX$AGENT_DIR/swg-agent" "$PREFIX$NODED_DIR/swg-noded"; ok "installed agent + daemon"
[ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$NODED_DIR/" || true   # version stamp (update.sh reports it)
mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent" "$PREFIX/etc/swg-agent"

# Pre-install wg + awg tools regardless of what interfaces (if any) are configured now — so creating
# an interface later from the panel "just works" (the sandboxed agent can't apt-install at runtime).
info "Installing WireGuard + AmneziaWG tools (for future interface creation)"
ensure_wg_tools wg  || warn "wireguard tools not installed — wg interface creation will need them"
ensure_wg_tools awg || warn "amneziawg tools not installed (the amnezia ppa is Ubuntu-only) — awg interface creation will need them"

# ───────────────────────── config.json (pull-only HTTPS) ─────────────────────────
IFJSON=""; sep=""
for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
  _onb=""; iface_onboarded "$n" && _onb=', "onboarded": true'   # add-only (adopted interface — keep its peers)
  IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\", \"endpoint_host\": \"${IF_ENDPOINT[$n]:-}\"${_onb} }"; sep=$',\n'; done
# node-level endpoint_host is now a fallback (the panel uses each interface's own when blank); default it to the first interface's
if [ -z "$ENDPOINT_IP" ]; then for n in "${SELECTED[@]}"; do [ -n "${IF_ENDPOINT[$n]:-}" ] && { ENDPOINT_IP="${IF_ENDPOINT[$n]}"; break; }; done; fi
[ -z "$ENDPOINT_IP" ] && ENDPOINT_IP="$(detect_public_ip)"
VERIFY_JSON=$([ "$TLS_VERIFY" = yes ] && echo true || echo false)
FP=""; [ -n "$TLS_FINGERPRINT" ] && FP=$',\n    "fingerprint": "'"$TLS_FINGERPRINT"'"'
writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${ENDPOINT_IP}",
  "dns": ["${DNS}"],
  "panel": {
    "url": "${PANEL_URL}",
    "token": "${NODE_TOKEN}",
    "verify": ${VERIFY_JSON}${FP}
  },
  "node": {
    "interval": ${INTERVAL},
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
warn "config.json holds the node key (mode 640, root:root). Treat it as a secret."

# ───────────────────────── daemon service (root) ─────────────────────────
writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to panel) — ${NODE_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${NODED_DIR}/swg-noded
Environment=SWG_AGENT_CONFIG=/etc/swg-agent/config.json
Environment=SWG_NODED_STATE=/var/lib/swg-noded
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=true
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# ───────────────────────── enable ─────────────────────────
info "Enable daemon"
run systemctl daemon-reload
run systemctl enable --quiet swg-noded
# restart (not just enable --now): on a RE-RUN that added interfaces, swg-noded is already running and
# reads config.json only at startup — so without a restart the new interfaces never reach the panel.
run systemctl restart swg-noded || warn "couldn't start swg-noded"
# Clear a stale convert-recovery marker now that the node is wired — but NOT when we're a STEP inside a
# docker→bare convert (SWG_CONVERT / SWG_TURN_ADD). convert.sh still has to migrate the turn-proxies and move
# the old docker dir aside after we return; it owns the marker and clears it (clear_recovery) only when the
# WHOLE convert is done. Clearing here would strand an interrupt after this point with no resume offer.
$DRYRUN || [ -n "${SWG_CONVERT:-}${SWG_TURN_ADD:-}" ] || rm -f /var/lib/swg-recovery 2>/dev/null || true

# during a convert, skip this summary entirely — convert.sh prints ONE final combined summary (interfaces +
# migrated turn-proxies) after. The "node is up — migrating turn-proxies next" line is enough here.
if [ "${SWG_CONVERT:-}" = 1 ]; then
  echo; ok "Node '$(bb "$NODE_NAME")' is up — migrating turn-proxies next…"
  exit 0
fi
echo; ok "Node '$(bb "$NODE_NAME")' install complete."
echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
echo "  Node      $(bb "$NODE_NAME")  →  syncs to $(bb "$PANEL_URL") every ${INTERVAL}s"
if [ "${#SELECTED[@]}" -gt 0 ]; then echo; echo "  $(b 'Interfaces') (manage peers in the panel):"
  for n in "${SELECTED[@]}"; do c="${IF_CONF[$n]:-}"
    printf '    %s %-9s %s  %s  mtu %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$n")")" "${IF_CMD[$n]:-?}" \
      "$(bb "${IF_ENDPOINT[$n]:-$ENDPOINT_IP}:$(conf_get "$c" ListenPort)")" "$(b "$(conf_get "$c" Address)")" "$(conf_get "$c" MTU)"
  done
fi
detect_turn
if [ "${#TP_LISTEN[@]}" -gt 0 ]; then echo; echo "  $(b 'Turn-proxy') instances:"
  for n in "${!TP_LISTEN[@]}"; do _fw="$(fwd_ifaces "${TP_CONNECT[$n]}")"
    printf '    %s %s → %s%s\n' "$(col "$C_GREEN" "$(printf '%-22s' "$n")")" "$(bb "${TP_LISTEN[$n]}")" "$(b "${TP_CONNECT[$n]}")" "${_fw:+ $(col "$C_GREEN" "($_fw)")}"
  done
fi
echo
echo "  Manage    each interface's ingress/egress IPs + egress NIC anytime in the panel → $(b Interfaces)"
echo "  Edit      interfaces in $(b /etc/amnezia/amneziawg/) / $(b /etc/wireguard/)  ·  turn-proxies in $(b /etc/systemd/system/)  ·  daemon $(b /etc/swg-agent/config.json)"
echo "  Logs      $(b 'journalctl -u swg-noded -f')  ·  turns green in the panel's Nodes screen in ~${INTERVAL}s"
[ "$VERIFY_JSON" = false ] && [ -z "$TLS_FINGERPRINT" ] && echo "  TLS       not verifying the panel cert (self-signed) — set TLS_FINGERPRINT to pin it"
if $DRYRUN; then echo; ok "DRY RUN done — inspect ./dryrun"; fi   # NB: an `if` (not `$DRYRUN && {…}`) so a non-dry-run doesn't make the script's LAST command exit non-zero (convert.sh read that as "install-node.sh reported an error")
exit 0   # reaching here = success (every fatal error die'd with exit 1 earlier; a single interface that couldn't come up is a non-fatal warning)
