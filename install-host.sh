#!/usr/bin/env bash
# install-host.sh — set up the swg-panel host (server + UI + collector + receiver).
#
# Two roles, chosen in Step 1 (or via ROLE): master or host.
#   master  panel + this box also runs wg/awg interfaces (an entry server)
#   host    panel only; wg/awg nodes are deployed separately
#
# Fill the CONFIG block to run unattended, or leave blanks to be prompted.
# Run as root. Use --dry-run to render every file under ./dryrun and execute nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
METHOD="${METHOD:-baremetal}"          # baremetal (systemd). For Docker, use docker-compose instead.
ROLE="${ROLE:-}"                       # master (panel + this box is an entry server) | host (panel only)
HOST_NODE_NAME="${HOST_NODE_NAME:-}"   # node name for THIS box (master only)
HOST_ENDPOINT_IP="${HOST_ENDPOINT_IP:-}" # public IP clients dial for this box's wg (master only)
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = manage all detected; master only)

PANEL_DOMAIN="${PANEL_DOMAIN:-}"       # panel URL: IP, host, or host/subpath (e.g. vpn.example.com/swg). Blank = this host's IP.
STORE_CONFIGS="${STORE_CONFIGS:-false}"

SERVE_MODE="${SERVE_MODE:-}"           # internal (self-contained) | nginx | caddy | skip  (blank = ask)
# TLS — how to obtain the certificate:
TLS_MODE="${TLS_MODE:-}"               # cloudflare | letsencrypt | selfsigned | skip  (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare: API token with Zone:DNS:Edit
CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-}"     # cloudflare: optional account id
CF_ORIGIN_KEY="${CF_ORIGIN_KEY:-}"     # cf15: Cloudflare Origin CA Key (My Profile → API Tokens → Origin CA Key)
CERT_FULLCHAIN="${CERT_FULLCHAIN:-}"   # skip-with-own-cert: path to fullchain.pem
CERT_KEY="${CERT_KEY:-}"               # skip-with-own-cert: path to private key.pem
BASIC_USER="${BASIC_USER:-admin}"
BASIC_PASS="${BASIC_PASS:-}"           # blank -> random, printed at the end

# Remote nodes are NOT listed here — add them in the panel's Nodes screen, which
# issues a one-time token + an install-node.sh command to run on each server.

# paths / identities (defaults are sane)
PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
ETC_DIR="${ETC_DIR:-/etc/swg-panel}"
STATE_DIR="${STATE_DIR:-/var/lib/swg-panel}"
STATS_DIR="${STATS_DIR:-/var/www/wgstats}"
PANEL_USER="${PANEL_USER:-swgpanel}"
PORT="${PORT:-}"
PANEL_BASE="${PANEL_BASE:-}"           # derived from PANEL_DOMAIN's path (e.g. /swg); blank = served at root
TLS_DIR="${TLS_DIR:-/etc/swg-panel/tls}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/www/acme}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PALETTE=("#34d399" "#22d3ee" "#c084e8" "#f0913c" "#e8c04b" "#60a5fa" "#f0596b")

# ── colours / styling (honour NO_COLOR + non-tty) ──
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; fi
b(){   printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
info(){ echo "${C_CYAN}▸${RESET} ${BOLD}$*${RESET}"; }   # every ▸ line is bold
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
writef(){ # writef <abs_path> <mode>   (content on stdin)
  local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"
  chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }   # menu <styled-label> <description>

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

# ── input validators (0 = ok) ──
v_role(){    case "$1" in master|host) return 0;; *) return 1;; esac; }
v_tls(){     case "$1" in cloudflare|letsencrypt|selfsigned|skip) return 0;; *) return 1;; esac; }
v_serve(){   case "$1" in internal|nginx|caddy|skip) return 0;; *) return 1;; esac; }
v_proto(){   case "$1" in a|awg|amneziawg|w|wg|wireguard) return 0;; *) return 1;; esac; }
v_ip(){      printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1
             local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; return 0; }
v_host(){    v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_url(){     case "$1" in ""|*" "*) return 1;; esac
             local h="${1#http://}"; h="${h#https://}"; h="${h%%/*}"; h="${h%%:*}"; v_host "$h"; }
v_port(){    case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
v_name(){    case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_user(){    case "$1" in ""|*:*|*" "*) return 1;; esac; [ "${#1}" -le 40 ]; }
v_email(){   case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }
v_cftoken(){ [ -n "$1" ] && [ "${#1}" -ge 10 ]; }
v_cforigin(){ [ -n "$1" ] && [ "${#1}" -ge 20 ]; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }

# ask_choice <prompt> <default> <var> "<opt…>"  — re-prompts on bad input; ' --force' overrides
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done
    warn "ignoring invalid $var='${!var}' (expected: $opts)"; fi
  while :; do
    if read -rp "$p [$(col "$C_BLUE" "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no
    case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
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
  while :; do
    if read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
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
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  printf '%s' "$ip"; }
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

parse_panel_url(){ # parse_panel_url <input> -> sets PANEL_HOST_NOPORT, PANEL_BASE, URL_PORT
  local u="$1" hostport rest
  u="${u#http://}"; u="${u#https://}"; u="${u%/}"
  hostport="${u%%/*}"                       # host[:port]
  rest="${u#"$hostport"}"                    # remaining /path (may be empty)
  PANEL_BASE="$rest"; [ "$PANEL_BASE" = "/" ] && PANEL_BASE=""
  PANEL_BASE="${PANEL_BASE%/}"               # no trailing slash
  case "$hostport" in
    *:*) PANEL_HOST_NOPORT="${hostport%%:*}"; URL_PORT="${hostport##*:}";;
    *)   PANEL_HOST_NOPORT="$hostport"; URL_PORT="";;
  esac
}

# ───────────────────────── wg/awg detection ─────────────────────────
declare -A IF_CMD IF_CONF
detect_wg(){ # scan everything under /etc/amnezia (any subdir) for awg, and /etc/wireguard for wg
  IF_CMD=(); IF_CONF=(); local f n
  if [ -d /etc/amnezia ]; then
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  fi
  for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
}
choose_ifaces(){ # populate SELECTED[] — all detected interfaces are managed; 'new' creates more
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    info "Checking for wg / awg on this host…"
    if [ "${#IF_CMD[@]}" -eq 0 ]; then
      warn "No wg / awg interfaces found in /etc/wireguard or /etc/amnezia."
      local doit; ask_yn "Create one now? (installs WireGuard / AmneziaWG only if missing)" y doit
      [ "$doit" = yes ] && create_iface
      detect_wg
      [ "${#IF_CMD[@]}" -eq 0 ] && die "No interface. Create one, then re-run (or set MANAGE_IFACES)."
    fi
    local names=() pick n
    while :; do
      detect_wg; names=("${!IF_CMD[@]}")
      echo
      printf "  Available interfaces:"
      for n in "${names[@]}"; do printf ' %s %s' "$(col "$C_GREEN" "$n")" "$(b "(${IF_CMD[$n]})")"; done
      echo; echo
      # print the prompt with printf (NOT read -p) so it always shows; never hide it via 2>/dev/null
      printf '  Press %s to proceed with the setup or enter "%s" to create an additional interface: ' "$(b Enter)" "$(col "$C_BLUE" new)"
      if ! read -r pick </dev/tty; then
        echo; warn "no interactive input — managing all detected interfaces"; break
      fi
      pick="${pick//[[:space:]]/}"
      [ "$pick" = new ] && { create_iface; continue; }
      [ -z "$pick" ] && break
      warn "type nothing to proceed, or \"new\" to add another interface"
    done
    SELECTED=("${names[@]}")          # every detected interface ends up in the web panel
  fi
  detect_wg
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }; done
  [ "${#SELECTED[@]}" -gt 0 ] || die "no interfaces selected"
  ok "Managing: $(b "$(col "$C_GREEN" "${SELECTED[*]}")")"
}

# ───────────────────────── turn-proxy (vk-turn-proxy) ─────────────────────────
# Tunnels WireGuard/AmneziaWG through VK/Yandex TURN servers. Config is the systemd
# unit's CLI args: -listen <pub-ip:port>  -connect <wg-ip:port>. We detect any such
# unit, can install the binary from a fork's GitHub releases, and record listen→connect
# so the panel can later tell a turn-proxied client (peer endpoint IP == a turn listen IP)
# from a direct wg/awg one. https://github.com/cacggghp/vk-turn-proxy
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
TURN_RECORD="${TURN_RECORD:-/etc/swg-agent/turn-proxy.json}"
declare -A TP_LISTEN TP_CONNECT TP_WRAP
turn_repo_owner(){ case "$1" in
  wings) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/vk-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  main) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }   # 32-byte key as 64 hex chars
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Per-fork obfuscation flags (verified from each binary's -h). Echoes the flags WITH a
# freshly generated -wrap-key baked in (kiper292 has no wrap support → empty).
turn_wrap_flags(){ local k; case "$1" in
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  wings)        k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  *) printf '';; esac; }
turn_wg_ports(){   # echo "<iface>:<ListenPort>" for every interface managed in the wg/awg step
  local n p
  for n in ${SELECTED[@]+"${SELECTED[@]}"}; do
    [ -n "${IF_CONF[$n]:-}" ] || continue
    p="$(grep -iE '^[[:space:]]*ListenPort[[:space:]]*=' "${IF_CONF[$n]}" 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//; s/[^0-9].*//')"
    [ -n "$p" ] && printf '%s:%s\n' "$n" "$p"
  done
}
detect_turn(){   # any systemd unit whose ExecStart carries both -listen and -connect is a turn-proxy
  TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local u name exe lis con wk
  for u in /etc/systemd/system/*.service; do
    [ -e "$u" ] || continue
    exe="$(sed -n 's/^ExecStart=//p' "$u" 2>/dev/null | head -1)"
    case "$exe" in *-listen*-connect*|*-connect*-listen*) ;; *) continue;; esac
    name="$(basename "$u" .service)"
    lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
    con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
    wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')"
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"
  done
}
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }   # turn_latest_tag <owner/repo>
  curl -fsSL "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ # <key> <owner/repo> <listen ip:port> <connect ip:port> <extra-flags>
  local key="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  dir="$TURN_DIR/$key"; bin="$dir/server"; svc="vk-turn-proxy-$key"
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$dir"
  info "Installing $owner ($listen → $connect)…"
  if $DRYRUN; then echo "    [skip] curl -fsSL $url -o $bin"
  elif ! { curl -fsSL "$url" -o "$PREFIX$bin" && chmod +x "$PREFIX$bin"; }; then
    warn "download failed ($url) — skipping this turn-proxy"; return 0
  fi
  ver="$(turn_latest_tag "$owner")"
  printf '%s\n' "$owner"        | writef "$dir/repo.txt" 644
  printf '%s\n' "${ver:-unknown}" | writef "$dir/version.txt" 644
  writef "/etc/systemd/system/$svc.service" 600 <<EOF
[Unit]
Description=vk-turn-proxy ($owner) — ${listen} → ${connect}
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=${bin} -listen ${listen} -connect ${connect} ${extra}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  run systemctl daemon-reload; run systemctl enable --now "$svc" || warn "couldn't start $svc"
  ok "installed turn-proxy $(col "$C_GREEN" "$key") ($owner ${ver:-?}) — $listen → $connect"
}
install_turn_proxy(){   # repo selection + params, then install
  echo
  menu "$(col "$C_BLUE" wings)"        "For Android — https://github.com/WINGS-N/vk-turn-proxy"
  menu "$(col "$C_BLUE" samosvalishe)" "For Android — https://github.com/samosvalishe/vk-turn-proxy"
  menu "$(col "$C_BLUE" kiper292)"     "For Android — https://github.com/kiper292/vk-turn-proxy"
  menu "$(col "$C_BLUE" anton48)"      "For iOS — https://github.com/anton48/vk-turn-proxy"
  local sel=""; ask_choice "Select turn-proxy repository or enter $(col "$C_RED" skip) to just proceed with the node setup" "skip" sel "wings samosvalishe kiper292 anton48 skip"
  [ "$sel" = skip ] && return 0
  local owner pub port connect extra; owner="$(turn_repo_owner "$sel")"
  ask_valid "Public IP this turn-proxy is reached at" "$(detect_public_ip)" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "56000" port v_port "port must be 1–65535"
  local ports defport=51820 disp n p proto first; ports="$(turn_wg_ports)"
  if [ -n "$ports" ]; then
    defport="$(printf '%s\n' "$ports" | head -1 | cut -d: -f2)"; disp=""; first=1
    while IFS=: read -r n p; do proto="${IF_CMD[$n]:-wg}"
      [ "$first" = 1 ] && first=0 || disp+=", "
      disp+="$(col "$C_BLUE" "$p") ($(col "$C_GREEN" "$n") on $(b "$proto"))"
    done <<< "$ports"
    echo "  Available wg/awg ports: ${disp}"
  fi
  ask_valid "WireGuard/AmneziaWG address it forwards to (ip:port)" "127.0.0.1:${defport}" connect v_hostport "ip:port, e.g. 127.0.0.1:51820"
  local wrap extra; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  ask "Extra server flags (optional)" "" extra
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap${extra:+ $extra}"
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
choose_turn_proxy(){   # looped menu — list installed, Enter to proceed, "new" to install another
  info "Checking for turn-proxy servers on this host…"
  detect_turn
  local names ans n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    if [ "${#names[@]}" -eq 0 ]; then
      echo; warn "No turn-proxy servers found on this box."
      printf '  Press %s to skip and proceed with the setup or enter "%s" to install a turn-proxy server: ' "$(b Enter)" "$(col "$C_BLUE" new)"
    else
      echo; printf "  Installed turn-proxy servers:"
      for n in "${names[@]}"; do printf ' %s %s' "$(col "$C_GREEN" "$n")" "$(b "(${TP_LISTEN[$n]} → ${TP_CONNECT[$n]})")"; done
      echo; echo
      printf '  Press %s to proceed with the setup or enter "%s" to install another turn-proxy server: ' "$(b Enter)" "$(col "$C_BLUE" new)"
    fi
    if ! read -r ans 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    ans="${ans//[[:space:]]/}"
    [ "$ans" = new ] && { install_turn_proxy; continue; }
    [ -z "$ans" ] && break
    warn 'type nothing to proceed, or "new" to install a turn-proxy server'
  done
  write_turn_record
}

ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools + kernel module if missing (idempotent, non-fatal -> 0/1)
  local cmd="$1"
  have "$cmd" && return 0
  if [ "$cmd" = wg ]; then
    run apt-get update -qq || true; run apt-get install -y wireguard || true
  else
    run apt-get update -qq || true; run apt-get install -y software-properties-common || true
    run add-apt-repository -y ppa:amnezia/ppa || true; run apt-get update -qq || true; run apt-get install -y amneziawg || true
  fi
  $DRYRUN && return 0
  have "$cmd"               # success only if the tool is actually present now
}
awg_obfuscation(){ # emit AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, and a conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))   # v2 init/response junk sizes
  b1=$(( 5          + (RANDOM*RANDOM) % 900000000 ))       # four disjoint bands keep H1–H4
  b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))       # distinct and non-overlapping, all > 4
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 ))
  b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  # Conservative QUIC-Initial mimicry on I1 only (no <c> counters, no <t> — keeps amneziawg-go/Android working).
  # 0xc3 = long-header Initial first byte; 0x00000001 = QUIC v1; then random payload.
  printf 'I1 = <b 0xc300000001><r 1200>\n'
}
server_addr(){ # server_addr <cidr> -> "<first-host>/<prefix>"
  have python3 || die "python3 is required to compute the tunnel address (it's also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
create_iface(){ # prompt, gen server key, write conf (AWG v2 + QUIC I1, or plain WG), NAT it to the WAN, bring up, register
  local _proto proto name port subnet addr conf cmd priv dir wan up down idx defname defport defsub upok
  idx=${#IF_CMD[@]}                              # offset defaults so a 2nd/3rd iface doesn't collide
  ask_choice "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) proto=wg; cmd=wg;  dir=/etc/wireguard;;
                                 *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  defname="$([ "$cmd" = awg ] && echo "awg$idx" || echo "wg$idx")"
  while [ -n "${IF_CMD[$defname]:-}" ] || [ -e "/etc/amnezia/amneziawg/$defname.conf" ] || [ -e "/etc/wireguard/$defname.conf" ]; do
    idx=$((idx+1)); defname="$([ "$cmd" = awg ] && echo "awg$idx" || echo "wg$idx")"; done
  while :; do
    ask_valid "Interface name" "$defname" name v_iface "1–15 chars: letters, digits, - or _"
    if [ -n "${IF_CMD[$name]:-}" ] || [ -e "/etc/amnezia/amneziawg/$name.conf" ] || [ -e "/etc/wireguard/$name.conf" ]; then
      warn "interface '$name' already exists — pick another name"; name=""; continue
    fi
    break
  done
  defport=$((51820 + idx)); defsub="10.$(( (8 + idx) % 255 )).0.0/24"
  ask_valid "Listen port" "$defport" port v_port "port must be 1–65535"
  ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$defsub" subnet v_subnet "enter a CIDR, e.g. 10.8.0.0/24"
  ask_valid "WAN egress interface (clients are NAT'd out using this)" "$(detect_wan || echo eth0)" wan v_iface "enter a network interface name"
  addr="$(server_addr "$subnet")"; conf="$dir/$name.conf"
  if ! ensure_wg_tools "$cmd"; then warn "couldn't install $cmd tools — skipping interface '$name'"; return 0; fi
  # gateway plumbing: forward + masquerade the tunnel subnet out the WAN (bound to iface lifecycle)
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
  run sysctl -q -w net.ipv4.ip_forward=1
  if $DRYRUN; then priv="<generated-on-real-run>"
  elif ! priv="$("$cmd" genkey 2>/dev/null)" || [ -z "$priv" ]; then warn "'$cmd genkey' failed — skipping interface '$name'"; return 0; fi
  { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\n' "$priv" "$addr" "$port"
    printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
    if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
  # bring up — NON-FATAL: a port/subnet clash must not abort the whole install (set -e)
  upok=yes
  if [ "$cmd" = awg ]; then run awg-quick up "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable "awg-quick@$name" || true; }
  else                     run wg-quick  up "$name" || upok=no; [ "$upok" = yes ] && { run systemctl enable "wg-quick@$name"  || true; }; fi
  if [ "$upok" = no ]; then
    warn "couldn't bring up '$name' (a port or subnet may already be in use) — removing its conf; try again with different values"
    run rm -f "$conf"; return 0
  fi
  IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; LAST_IFACE="$name"
  ok "created $proto interface $(col "$C_GREEN" "$name") on :$port (server $addr, NAT out $wan)"
}

# ───────────────────────── prompts ─────────────────────────
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# ═══════════════ I. PANEL SETUP ═══════════════
echo; info "PANEL SETUP"

# Step 1 — server role
ROLE_SEL=""
case "$ROLE" in master|host+node) ROLE_SEL=master;; host) ROLE_SEL=host;; node) die "for a node-only box run install-node.sh, not this script";; esac
echo
echo "$(b 'Step 1. Server role:')"
echo
menu "$(b "$(col "$C_BLUE" 'master (default)')")" "Masternode — this server will host the panel and run WG/AWG interfaces"
menu "$(col "$C_BLUE" host)"                       "This server will host only the panel. WG/AWG nodes will be deployed separately"
ask_choice "Select role" "master" ROLE_SEL "master host"
case "$ROLE_SEL" in master) ROLE="host+node";; host) ROLE="host";; esac
HOST_HAS_WG=no; [ "$ROLE" = "host+node" ] && HOST_HAS_WG=yes

# Step 2 — panel URL (may include a subpath, e.g. vpn.example.com/swg)
echo
echo "$(b 'Step 2. Panel URL')"
echo
echo "      Where the panel is reached — an IP, a host, or a host with a subpath to"
echo "      live under an existing site (e.g. $(b 'vpn.example.com/swg'))."
echo
DEF_URL="$(detect_public_ip)"; [ -z "$DEF_URL" ] && DEF_URL=localhost
ask_valid "Enter panel URL (https://…)" "$DEF_URL" PANEL_DOMAIN v_url "enter a host or IP, optionally with a /subpath (e.g. vpn.example.com/swg)"
parse_panel_url "$PANEL_DOMAIN"
PANEL_DOMAIN="$PANEL_HOST_NOPORT"
[ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
[ -n "$PANEL_BASE" ] && ok "panel will be served under subpath ${PANEL_BASE}/"

# Step 3 — TLS certificate
echo
echo "$(b 'Step 3. TLS certificate')"
echo
menu "$(b "$(col "$C_BLUE" 'letsencrypt (default)')")" "Let's Encrypt cert via acme.sh HTTP-01 (needs port 80 reachable)"
menu "$(col "$C_BLUE" cloudflare)"                    "Let's Encrypt cert, validated via Cloudflare DNS-01 (no port 80) — needs a Zone:DNS:Edit+Read token + email"
menu "$(col "$C_BLUE" cf15)"                          "Cloudflare Origin certificate, 15 years — ONLY valid behind Cloudflare's proxy (orange cloud); needs the Origin CA Key"
menu "$(col "$C_BLUE" selfsigned)"                    "OK for testing"
menu "$(col "$C_GREY" skip)"                          "If you are planning to use your own certificate (or terminate TLS elsewhere)"
[ -z "$TLS_MODE" ] && [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] && TLS_MODE=skip
case "$TLS_MODE" in manual|none) TLS_MODE=skip;; esac
ask_choice "Select TLS certificate" "letsencrypt" TLS_MODE "letsencrypt cloudflare cf15 selfsigned skip"
# every public-CA / origin mode needs a real FQDN — check before asking for credentials
case "$TLS_MODE" in letsencrypt|cloudflare|cf15)
  case "$PANEL_DOMAIN" in *.*) : ;; *) die "TLS=$TLS_MODE needs a domain (FQDN) in the panel URL, not '$PANEL_DOMAIN' — re-run and pick selfsigned for an IP";; esac
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) : ;; *) die "TLS=$TLS_MODE needs a real domain (not an IP) — re-run and pick selfsigned for an IP";; esac ;;
esac
case "$TLS_MODE" in
  letsencrypt) ask_valid "ACME account email"                                     "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
  cloudflare)  ask_valid "Cloudflare API token (needs Zone:DNS:Edit + Zone:Read)" "" CF_TOKEN  v_cftoken "the API token can't be empty"
               ask_valid "ACME account email"                                     "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
  cf15)        warn "cf15 issues a Cloudflare Origin cert — it is ONLY trusted behind Cloudflare's proxy."
               warn "$PANEL_DOMAIN must be on Cloudflare with the orange cloud ON; a direct hit to the origin shows an untrusted cert."
               ask_valid "Cloudflare Origin CA Key (My Profile → API Tokens → Origin CA Key → View)" "" CF_ORIGIN_KEY v_cforigin "paste the Origin CA Key (starts with v1.0-…)";;
esac

# Step 4 — web server
echo
echo "$(b 'Step 4. Web server:')"
echo
menu "$(b "$(col "$C_BLUE" 'internal (default)')")" "Self-contained, no separate web-server is required"
menu "$(col "$C_BLUE" nginx)"                       "Web content will be served via an Nginx reverse proxy"
menu "$(col "$C_BLUE" caddy)"                       "Web content will be served via a Caddy reverse proxy"
menu "$(col "$C_GREY" skip)"                        "If you are planning to configure the web server manually"
case "$SERVE_MODE" in standalone) SERVE_MODE=internal;; esac
ask_choice "Select web server" "internal" SERVE_MODE "internal nginx caddy skip"

# port: internal serves the public port itself; proxy/manual modes keep the panel on a loopback port
if [ "$SERVE_MODE" = internal ]; then
  [ -z "$PORT" ] && PORT="${URL_PORT:-443}"
  ask_valid "Public HTTPS port for the panel" "$PORT" PORT v_port "port must be 1–65535"
else
  [ -z "$PORT" ] && PORT="${URL_PORT:-8088}"
fi

# Admin login — username suggested as admin + 3 random digits; password auto-generated (printed at the end).
[ -z "$BASIC_PASS" ] && BASIC_PASS="$(head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16)"
if [ "${BASIC_USER}" = admin ]; then BASIC_USER="admin$(( RANDOM % 900 + 100 ))"; fi
ask_valid "Panel admin username" "$BASIC_USER" BASIC_USER v_user "1–40 chars, no ':' or spaces"

# ═══════════════ II. NODE SETUP (master only) ═══════════════
declare -a SELECTED
if [ "$HOST_HAS_WG" = yes ]; then
  echo; info "NODE SETUP"
  echo
  echo "$(b 'Step 1. Node name for THIS box')"
  echo
  ask_valid "Node name for THIS box" "$(hostname -s 2>/dev/null || hostname)" HOST_NODE_NAME v_name "1–40 chars: letters, digits, - or _"
  echo
  echo "$(b 'Step 2. Endpoint IP clients dial for THIS box')"
  echo
  ask_valid "Endpoint IP clients dial for THIS box" "$(detect_public_ip)" HOST_ENDPOINT_IP v_host "enter an IP address or hostname"
  echo
  echo "$(b 'Step 3. WireGuard / AmneziaWG setup')"
  echo
  choose_ifaces
  echo
  echo "$(b 'Step 4. TURN-PROXY setup') (https://github.com/cacggghp/vk-turn-proxy)"
  echo
  choose_turn_proxy
fi

echo; info "Plan: method=$METHOD role=$ROLE serve=$SERVE_MODE tls=$TLS_MODE base=${PANEL_BASE:-/} store_configs=$STORE_CONFIGS"

# ───────────────────────── users / dirs ─────────────────────────
info "Users, groups, directories"
run groupadd -f swg
id "$PANEL_USER" >/dev/null 2>&1 || run useradd -r -g swg -d "$STATE_DIR" -s /usr/sbin/nologin "$PANEL_USER"
run usermod -d "$STATE_DIR" -g swg "$PANEL_USER"
for d in "$PANEL_DIR" "$ETC_DIR" "$STATE_DIR" "$STATS_DIR"; do mkdir -p "$PREFIX$d"; done
run chown "$PANEL_USER:swg" "$STATE_DIR"; run chmod 750 "$STATE_DIR"
run chown "$PANEL_USER:swg" "$STATS_DIR"; run chmod 2775 "$STATS_DIR"   # panel writes node snapshots here for the dashboard
[ "$STORE_CONFIGS" = true ] && { mkdir -p "$PREFIX$STATE_DIR/configs"; run chown "$PANEL_USER:swg" "$STATE_DIR/configs"; run chmod 750 "$STATE_DIR/configs"; }

# ───────────────────────── panel files ─────────────────────────
info "Panel application"
for f in swg-panel-server index.html app.css app.js reconcile.js; do
  [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"
done
mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/swg-panel-server" "$PREFIX$PANEL_DIR/"; chmod 755 "$PREFIX$PANEL_DIR/swg-panel-server"
for f in index.html app.css app.js reconcile.js; do mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/$f" "$PREFIX$PANEL_DIR/"; done
mkdir -p "$PREFIX$PANEL_DIR/vendor"; cp "$SRC/vendor/qrcode.js" "$PREFIX$PANEL_DIR/vendor/"
[ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$PANEL_DIR/" || true   # version stamp (update.sh reports it)
ok "installed panel + SPA to $PANEL_DIR"
mkdir -p "$PREFIX$STATE_DIR"; [ -f "$PREFIX$STATE_DIR/users.json" ] || { echo '{}' > "$PREFIX$STATE_DIR/users.json"; run chown "$PANEL_USER:swg" "$STATE_DIR/users.json"; ok "seeded empty users.json"; }

# ───────────────────────── host-as-node (this box is also an entry server) ─────────────────────────
LOCAL_TOKHASH=""
if [ "$HOST_HAS_WG" = yes ]; then
  info "This box as a node: agent + swg-noded (syncs to the local panel over HTTPS)"
  mkdir -p "$PREFIX$AGENT_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; chmod 755 "$PREFIX$AGENT_DIR/swg-agent"
  mkdir -p "$PREFIX$NODED_DIR"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"; chmod 755 "$PREFIX$NODED_DIR/swg-noded"
  [ -f "$SRC/VERSION" ] && cp "$SRC/VERSION" "$PREFIX$NODED_DIR/" || true
  mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent"

  # the local node always reaches the local panel on loopback (works for every serve mode);
  # scheme is https only when the panel terminates TLS itself (internal mode with a cert).
  LOCAL_SCHEME=http
  [ "$SERVE_MODE" = internal ] && [ "$TLS_MODE" != skip ] && LOCAL_SCHEME=https
  LOCAL_PANEL_URL="${LOCAL_SCHEME}://127.0.0.1:${PORT}${PANEL_BASE}"

  if [ -f "$PREFIX/etc/swg-agent/config.json" ]; then
    ok "keeping existing /etc/swg-agent/config.json (local node already enrolled)"
  else
    # auto-enroll: mint a token for the local node; its hash goes into nodes.json below
    LOCAL_TOKEN="$(head -c18 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')"
    LOCAL_TOKHASH="$(python3 -c 'import hashlib,os,base64,sys;t=sys.argv[1].encode();s=os.urandom(16);h=hashlib.pbkdf2_hmac("sha256",t,s,200000);print("pbkdf2_sha256$200000$"+base64.b64encode(s).decode()+"$"+base64.b64encode(h).decode())' "$LOCAL_TOKEN")"
    IFJSON=""; sep=""
    for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
      IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\" }"; sep=$',\n'; done
    writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${HOST_ENDPOINT_IP}",
  "dns": ["1.1.1.1"],
  "panel": {
    "url": "${LOCAL_PANEL_URL}",
    "token": "${LOCAL_TOKEN}",
    "verify": false
  },
  "node": {
    "interval": 5,
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
  fi
  # swg-noded runs as ROOT (samples kernel wg + runs the agent which writes /etc). ProtectSystem=true keeps /etc writable.
  writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to local panel) — ${HOST_NODE_NAME}
After=network-online.target swg-panel-server.service
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
fi

# ───────────────────────── nodes.json + fleet.json ─────────────────────────
info "nodes.json + fleet.json"
if [ "$HOST_HAS_WG" = yes ] && [ -n "$LOCAL_TOKHASH" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{
  "${HOST_NODE_NAME}": { "name": "${HOST_NODE_NAME}", "color": "${PALETTE[0]}", "endpoint_host": "${HOST_ENDPOINT_IP}", "stats_file": "stats-${HOST_NODE_NAME}.json", "token_hash": "${LOCAL_TOKHASH}", "created": $(date +%s 2>/dev/null || echo 0) }
}
EOF
elif [ ! -f "$PREFIX$STATE_DIR/nodes.json" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{}
EOF
fi
run chown "$PANEL_USER:swg" "$STATE_DIR/nodes.json" 2>/dev/null || true
writef /etc/swg-panel/fleet.json 640 <<EOF
{
  "roster_path":   "${STATE_DIR}/users.json",
  "nodes_path":    "${STATE_DIR}/nodes.json",
  "stats_dir":     "${STATS_DIR}",
  "store_configs": ${STORE_CONFIGS},
  "config_dir":    "${STATE_DIR}/configs",
  "node_interval": 5
}
EOF
run chown "$PANEL_USER:swg" "$ETC_DIR/fleet.json" 2>/dev/null || true

# ───────────────────────── panel-server service ─────────────────────────
write_panel_unit(){   # bind/TLS/base depend on SERVE_MODE; called from the serve section
  local bind="127.0.0.1" extra=""
  extra="Environment=SWG_PANEL_AUTH=${ETC_DIR}/auth"            # panel does its own login in every serve mode
  [ -n "$PANEL_BASE" ] && extra="$extra
Environment=SWG_PANEL_BASE=${PANEL_BASE}"
  if [ "$SERVE_MODE" = internal ]; then
    bind="0.0.0.0"                                              # internal mode faces the network directly
    [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] && extra="$extra
Environment=SWG_PANEL_TLS_CERT=${CERT_FULLCHAIN}
Environment=SWG_PANEL_TLS_KEY=${CERT_KEY}"
    [ "${PORT}" -lt 1024 ] 2>/dev/null && extra="$extra
AmbientCapabilities=CAP_NET_BIND_SERVICE"
  fi
  writef /etc/systemd/system/swg-panel-server.service 644 <<EOF
[Unit]
Description=swg-panel broker
After=network.target

[Service]
Type=simple
User=${PANEL_USER}
ExecStart=${PANEL_DIR}/swg-panel-server
Environment=SWG_PANEL_FLEET=${ETC_DIR}/fleet.json
Environment=SWG_PANEL_WEB=${PANEL_DIR}
Environment=SWG_PANEL_HOST=${bind}
Environment=SWG_PANEL_PORT=${PORT}
${extra}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${ETC_DIR} ${STATE_DIR} ${STATS_DIR}
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
}

# (no push receiver — nodes connect outbound over HTTPS; enroll them in the Nodes screen)

# ───────────────────────── login + TLS + serve mode ─────────────────────────
mk_auth_file(){   # panel login file (pbkdf2) — used by every serve mode so the Account tab works
  mkdir -p "$PREFIX$ETC_DIR"
  if $DRYRUN; then echo "    [skip] write ${ETC_DIR}/auth (pbkdf2 login for $BASIC_USER)"
    printf '%s:pbkdf2_sha256$200000$DRYRUN$DRYRUN\n' "$BASIC_USER" > "$PREFIX$ETC_DIR/auth"
  else
    python3 - "$BASIC_USER" "$BASIC_PASS" > "$PREFIX$ETC_DIR/auth" <<'PYAUTH'
import sys, os, hashlib, base64
u, pw = sys.argv[1], sys.argv[2]
salt = os.urandom(16); it = 200000
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
print("%s:pbkdf2_sha256$%d$%s$%s" % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
PYAUTH
  fi
  chmod 640 "$PREFIX$ETC_DIR/auth" 2>/dev/null || true; run chown root:swg "$ETC_DIR/auth"
  ok "login: $BASIC_USER  (stored hashed in ${ETC_DIR}/auth)"
}
cert_perms(){ run chown root:swg "$TLS_DIR/fullchain.pem" "$TLS_DIR/key.pem" 2>/dev/null || true
  chmod 644 "$PREFIX$TLS_DIR/fullchain.pem" 2>/dev/null || true; chmod 640 "$PREFIX$TLS_DIR/key.pem" 2>/dev/null || true; }
san_for(){ case "$1" in *[a-zA-Z]*) echo "DNS:$1";; *) echo "IP:$1";; esac; }
find_acme(){ ACME=""; local a; for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do [ -n "$a" ] && [ -x "$a" ] && { ACME="$a"; return 0; }; done; return 1; }
ensure_acme(){ find_acme && return 0
  info "Installing acme.sh"; run sh -c "curl -fsSL https://get.acme.sh | sh -s email=${ACME_EMAIL:-admin@$PANEL_DOMAIN}"
  find_acme && return 0; $DRYRUN && { ACME=/root/.acme.sh/acme.sh; return 0; }
  die "acme.sh not found after install — install it manually or use TLS=selfsigned/skip"; }
mk_selfsigned(){ CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  if $DRYRUN; then echo "    [skip] openssl self-signed -> $TLS_DIR (CN=$PANEL_DOMAIN)"; : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"
  else run openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$CERT_KEY" -out "$CERT_FULLCHAIN" -subj "/CN=${PANEL_DOMAIN}" -addext "subjectAltName=$(san_for "$PANEL_DOMAIN")"; fi
  cert_perms; ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; }
use_provided_certs(){   # skip-with-own-cert: copy caller-supplied cert into $TLS_DIR; 0 if used, 1 if none
  [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] || return 1
  mkdir -p "$PREFIX$TLS_DIR"
  $DRYRUN || { cp "$CERT_FULLCHAIN" "$PREFIX$TLS_DIR/fullchain.pem"; cp "$CERT_KEY" "$PREFIX$TLS_DIR/key.pem"; }
  CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; cert_perms
  ok "using provided certificate (copied into $TLS_DIR)"; return 0; }
mk_cf_origin(){   # cf15: request a 15-year Cloudflare Origin certificate via the CF API (Origin CA Key)
  CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  [ -n "${CF_ORIGIN_KEY:-}" ] || die "cf15 needs CF_ORIGIN_KEY (Cloudflare Origin CA Key)"
  if $DRYRUN; then echo "    [skip] request Cloudflare Origin certificate (15y, origin-ecc) for $PANEL_DOMAIN"
    : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"; cert_perms; ok "cf15 origin certificate (dry-run placeholder)"; return 0; fi
  local key csr cert
  key="$(openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null)" || die "openssl: EC key generation failed"
  csr="$(printf '%s\n' "$key" | openssl req -new -key /dev/stdin -subj "/CN=${PANEL_DOMAIN}" 2>/dev/null)" || die "openssl: CSR generation failed"
  info "Requesting a 15-year Cloudflare Origin certificate for $PANEL_DOMAIN…"
  cert="$(CF_ORIGIN_KEY="$CF_ORIGIN_KEY" python3 - "$PANEL_DOMAIN" "$csr" <<'PY'
import sys, os, json, urllib.request, urllib.error
domain, csr = sys.argv[1], sys.argv[2]
body = json.dumps({"hostnames": [domain], "requested_validity": 5475,
                   "request_type": "origin-ecc", "csr": csr}).encode()
req = urllib.request.Request("https://api.cloudflare.com/client/v4/certificates", data=body, method="POST",
      headers={"Content-Type": "application/json", "X-Auth-User-Service-Key": os.environ["CF_ORIGIN_KEY"]})
try:
    with urllib.request.urlopen(req, timeout=30) as r: d = json.load(r)
except urllib.error.HTTPError as e:
    d = json.load(e)
except Exception as e:
    sys.stderr.write(str(e)); sys.exit(1)
if d.get("success"): sys.stdout.write(d["result"]["certificate"])
else: sys.stderr.write(json.dumps(d.get("errors", d))[:300]); sys.exit(1)
PY
)" || die "Cloudflare Origin CA request failed — check the Origin CA Key and that $PANEL_DOMAIN is on this Cloudflare account"
  printf '%s\n' "$cert" > "$PREFIX$CERT_FULLCHAIN"
  printf '%s\n' "$key"  > "$PREFIX$CERT_KEY"
  cert_perms; ok "issued Cloudflare Origin certificate (15y) for ${PANEL_DOMAIN} — valid only behind Cloudflare's proxy"; }

# ---- internal: the panel serves its own TLS; cert lands in $TLS_DIR ----
obtain_cert_internal(){
  mkdir -p "$PREFIX$TLS_DIR"
  case "$TLS_MODE" in
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — panel will serve plain HTTP"; }; return 0;;
    selfsigned) mk_selfsigned;;
    cf15) mk_cf_origin;;
    letsencrypt|cloudflare)
      ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs a CF token (re-run Step 3, or set CF_TOKEN)"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing $PANEL_DOMAIN via Let's Encrypt — DNS-01 challenge through Cloudflare (can take ~30–60s while DNS propagates)…"
      else args+=(--standalone); info "Issuing $PANEL_DOMAIN via Let's Encrypt — HTTP-01 (acme standalone needs :80 free)…"; fi
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      # Re-run? acme.sh already manages this domain → install the existing cert instead of
      # re-issuing (a fresh --issue errors on the existing domain key). Renewals run from acme's cron.
      if ! $DRYRUN && "$ACME" --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then
        ok "acme.sh already has a cert for $PANEL_DOMAIN — installing it (auto-renews via acme's cron)"
      else
        local rc=0; run "$ACME" "${args[@]}" || rc=$?
        # acme.sh exit 2 = RENEW_SKIP (a valid cert already exists, not due for renewal) — that's fine.
        if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
          if $DRYRUN || "$ACME" --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then
            warn "acme.sh exit $rc, but a cert for $PANEL_DOMAIN already exists — installing it."
          else
            warn "issuance failed (acme.sh exit $rc) — falling back to a self-signed cert."; mk_selfsigned; return
          fi
        fi
      fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" \
          --reloadcmd "chown root:swg $TLS_DIR/fullchain.pem $TLS_DIR/key.pem; chmod 640 $TLS_DIR/key.pem; systemctl restart swg-panel-server"
      cert_perms; ok "issued + installed certificate via $TLS_MODE (auto-renews)";;
    *) die "TLS must be cloudflare|letsencrypt|selfsigned|skip";;
  esac
}
serve_internal(){
  # acme's --install-cert reloadcmd runs `systemctl restart swg-panel-server` immediately,
  # so the unit must exist (and be loaded) BEFORE issuance — write+enable a TLS-less
  # placeholder first, then rewrite with the real cert paths and restart for real.
  write_panel_unit
  run systemctl daemon-reload
  run systemctl enable --now swg-panel-server
  obtain_cert_internal
  write_panel_unit
  run systemctl daemon-reload
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then run systemctl restart swg-panel-server; fi
  if command -v ufw >/dev/null 2>&1; then run ufw allow "${PORT}/tcp" 2>/dev/null || true; fi
  local sch="https"; [ -n "${CERT_FULLCHAIN:-}" ] || sch="http"
  [ "$sch" = http ] && warn "TLS skipped — login travels in the clear. Use selfsigned/letsencrypt/cloudflare for real use."
  ok "Internal: panel serves ${sch}://${PANEL_DOMAIN}:${PORT}${PANEL_BASE}/ directly (no extra web server)"
}

# ---- reverse-proxy (nginx / caddy): panel on loopback, proxy terminates TLS ----
setup_tls_proxy(){   # issue/locate a cert into $TLS_DIR for a reverse proxy to use
  case "$TLS_MODE" in
    selfsigned) mk_selfsigned;;
    cf15) mk_cf_origin;;
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — proxy will serve plain HTTP (or add your own cert)"; }; return 0;;
    letsencrypt|cloudflare)
      mkdir -p "$PREFIX$TLS_DIR"; ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs a CF token (re-run Step 3, or set CF_TOKEN)"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing $PANEL_DOMAIN via Let's Encrypt — DNS-01 challenge through Cloudflare (can take ~30–60s while DNS propagates)…"
      elif [ "$SERVE_MODE" = nginx ]; then args+=(--webroot "$ACME_WEBROOT")    # nginx already serves :80 for the challenge
      else args+=(--standalone); fi                                            # caddy not up yet → acme can hold :80
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      local reload="systemctl reload nginx"; [ "$SERVE_MODE" = caddy ] && reload="systemctl reload caddy"
      # Re-run? install the existing cert instead of re-issuing (avoids the domain-key error).
      if ! $DRYRUN && "$ACME" --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then
        ok "acme.sh already has a cert for $PANEL_DOMAIN — installing it (auto-renews via acme's cron)"
      else
        local rc=0; run "$ACME" "${args[@]}" || rc=$?
        if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ] && ! { $DRYRUN || "$ACME" --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; }; then
          warn "issuance failed (acme.sh exit $rc) — proxy will serve plain HTTP."; CERT_FULLCHAIN=""; CERT_KEY=""; return 0
        fi
      fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" --reloadcmd "$reload"
      cert_perms; ok "issued + installed certificate via $TLS_MODE";;
    *) die "TLS must be cloudflare|letsencrypt|selfsigned|skip";;
  esac
}
proxy_loc(){ [ -n "$PANEL_BASE" ] && printf '%s/' "$PANEL_BASE" || printf '/'; }   # nginx location path

write_vhost(){   # write_vhost bootstrap|tls    (nginx)
  local loc; loc="$(proxy_loc)"
  if [ "$1" = tls ]; then
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name ${PANEL_DOMAIN};
    ssl_certificate ${CERT_FULLCHAIN};
    ssl_certificate_key ${CERT_KEY};

    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  fi
  if [ -d /etc/nginx/sites-enabled ]; then run ln -sf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/sites-enabled/swg-panel.conf
  elif [ -d /etc/nginx/conf.d ]; then cp "$PREFIX/etc/nginx/sites-available/swg-panel.conf" "$PREFIX/etc/nginx/conf.d/swg-panel.conf"; fi
}
serve_nginx(){
  mkdir -p "$PREFIX$ACME_WEBROOT"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  write_vhost bootstrap
  run nginx -t && run systemctl reload nginx || warn "nginx -t failed (is nginx installed?) — fix, then: systemctl reload nginx"
  setup_tls_proxy
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then
    write_vhost tls
    run nginx -t && run systemctl reload nginx || warn "nginx -t failed after enabling TLS — check $CERT_FULLCHAIN"
    ok "nginx: TLS enabled for https://${PANEL_DOMAIN}${PANEL_BASE}/"
  else warn "nginx: serving on :80 without TLS — front with TLS before exposing."; fi
}

ensure_caddy_import(){   # make the main Caddyfile import our drop-in
  local main=/etc/caddy/Caddyfile
  if $DRYRUN; then echo "    [skip] ensure 'import conf.d/*.caddy' in $main"; return 0; fi
  mkdir -p /etc/caddy/conf.d; touch "$main"
  grep -qF 'conf.d/*.caddy' "$main" 2>/dev/null || printf '\nimport conf.d/*.caddy\n' >> "$main"
}
write_caddy_site(){
  local site="$PANEL_DOMAIN" tls="" handle="handle"
  [ -n "$PANEL_BASE" ] && handle="handle ${PANEL_BASE}/*"
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then tls="    tls ${CERT_FULLCHAIN} ${CERT_KEY}"
  elif [ "$TLS_MODE" = selfsigned ]; then tls="    tls internal"
  elif [ "$TLS_MODE" = skip ]; then site="http://${PANEL_DOMAIN}"; fi
  writef /etc/caddy/conf.d/swg-panel.caddy 644 <<EOF
${site} {
${tls}
    ${handle} {
        reverse_proxy 127.0.0.1:${PORT}
    }
}
EOF
  ensure_caddy_import
}
serve_caddy(){
  have caddy || warn "caddy not found — install it (https://caddyserver.com), then re-run or 'systemctl reload caddy'"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  setup_tls_proxy            # caddy isn't up yet, so acme standalone (:80) is free for letsencrypt
  write_caddy_site
  run systemctl reload caddy 2>/dev/null || run systemctl restart caddy 2>/dev/null || warn "couldn't (re)load caddy — start it after checking /etc/caddy/conf.d/swg-panel.caddy"
  local sch="https"; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && sch="http"
  ok "caddy: serving ${sch}://${PANEL_DOMAIN}${PANEL_BASE}/"
}

serve_skip(){
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  ok "Panel running on 127.0.0.1:${PORT}${PANEL_BASE} — configure your web server to proxy to it."
  echo "    nginx example:"
  echo "      location $(proxy_loc) { proxy_pass http://127.0.0.1:${PORT}; proxy_set_header Host \$host; }"
}

info "Login + TLS ($SERVE_MODE)"
mk_auth_file
case "$SERVE_MODE" in
  internal) serve_internal;;
  nginx)    serve_nginx;;
  caddy)    serve_caddy;;
  skip)     serve_skip;;
esac

# ───────────────────────── enable ─────────────────────────
info "Enable services"
run systemctl daemon-reload
[ "$HOST_HAS_WG" = yes ] && run systemctl enable --now swg-noded
run systemctl enable --now swg-panel-server
[ "$SERVE_MODE" = nginx ] && { run nginx -t && run systemctl reload nginx || warn "nginx -t failed; fix the vhost then: systemctl reload nginx"; }

# ───────────────────────── handoff ─────────────────────────
echo; ok "Host install complete."
case "$SERVE_MODE" in
  internal)
    SCH=https; [ -n "${CERT_FULLCHAIN:-}" ] || SCH=http
    PORTSUF=""; [ "$PORT" != 443 ] && PORTSUF=":${PORT}"
    echo "  UI:    ${SCH}://${PANEL_DOMAIN}${PORTSUF}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    command -v ufw >/dev/null 2>&1 || echo "         open TCP ${PORT} in your firewall if it isn't already"
    [ "$TLS_MODE" = selfsigned ] && echo "         self-signed cert — the browser warns once, that's expected"
    ;;
  nginx|caddy)
    SCH=https; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && SCH=http
    echo "  UI:    ${SCH}://${PANEL_DOMAIN}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    ;;
  skip)
    echo "  Panel: http://127.0.0.1:${PORT}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    echo "         point your web server at it (proxy ${PANEL_BASE:-/} → 127.0.0.1:${PORT})"
    ;;
esac
echo "  Local: curl -s 127.0.0.1:${PORT}${PANEL_BASE}/api/fleet"
echo
echo "Add entry servers from the UI: Nodes → Add node issues a one-time token and the"
echo "exact one-liner to run on each server (outbound HTTPS only — no inbound)."
[ "$HOST_HAS_WG" = yes ] && echo "This box is enrolled as node '${HOST_NODE_NAME}'; it appears in Nodes once swg-noded syncs."
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun"; }
