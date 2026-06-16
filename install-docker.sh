#!/usr/bin/env bash
# install-docker.sh — one-line Docker installer for swg-panel.
#
#   Panel only:        … | sudo bash -s docker -pass SECRET -domain panel.example.net
#   Panel + a node:    … | sudo bash -s docker --profile host-node -pass SECRET -key KEY -endpoint 203.0.113.7
#   Node only:         … | sudo bash -s docker --profile node -key KEY -host https://panel.example.net -endpoint 203.0.113.7
#
# Ensures Docker is present, stages the project under /opt/swg-panel-docker, writes a
# .env, and brings up the chosen compose profile. Run as root. --dry-run renders the
# .env under ./dryrun and runs no Docker commands.
#
#   --profile host|node|host-node   which compose profile (default host)
#   -pass <pw>      panel admin password     (-> PANEL_PASSWORD)
#   -domain <host>  panel domain/IP for cert (-> PANEL_DOMAIN)
#   -port <n>       host port for the panel  (-> PANEL_PORT, default 8443)
#   -key <tok>      node enrollment key      (-> NODE_TOKEN)
#   -host <url>     panel URL the node dials (-> PANEL_URL)
#   -endpoint <ip>  public IP clients dial   (-> NODE_ENDPOINT)
#   -iface <name>   node interface name      (-> NODE_IFACE, default awg0)
set -euo pipefail

# ───────────────────────── config (env or flags) ─────────────────────────
PROFILE="${PROFILE:-host}"
INSTALL_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
# Panel
PANEL_PASSWORD="${PANEL_PASSWORD:-}"
PANEL_USER="${PANEL_USER:-admin}"
PANEL_DOMAIN="${PANEL_DOMAIN:-}"        # host/IP only; a full URL (host[:port][/subpath]) is parsed in Step 1
PANEL_BASE="${PANEL_BASE:-}"            # optional subpath mount, e.g. /swg (also derivable from the URL)
PANEL_HOST_NOPORT=""; URL_PORT=""       # filled by parse_panel_url
TLS="${TLS:-}"                         # letsencrypt|cloudflare|cf15|selfsigned|none (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare DNS-01: API token with Zone:DNS:Edit + Zone:Read
CF_ORIGIN_TOKEN="${CF_ORIGIN_TOKEN:-${CF_ORIGIN_KEY:-}}"  # cf15: API token with Zone:SSL and Certificates:Edit
PANEL_PORT="${PANEL_PORT:-}"           # host-published port; blank = derive from URL, else 443 (Step 1)
# Node
PANEL_URL="${PANEL_URL:-}"
NODE_TOKEN="${NODE_TOKEN:-}"
NODE_ENDPOINT="${NODE_ENDPOINT:-${ENDPOINT_IP:-}}"
NODE_IFACE="${NODE_IFACE:-awg0}"
NODE_IFACES="${NODE_IFACES:-}"         # several interfaces: "name:port:addr[:proto],…"
NODE_LISTEN_PORT="${NODE_LISTEN_PORT:-51820}"
NODE_ADDRESS="${NODE_ADDRESS:-10.8.0.1/24}"
NODE_MTU="${NODE_MTU:-1280}"           # interface MTU; 1280 leaves headroom for turn-proxy obfuscation
NODE_PLAIN_WG="${NODE_PLAIN_WG:-}"     # yes = plain WireGuard; blank/no = AmneziaWG v2 (Step 2 sets it)
TLS_VERIFY="${TLS_VERIFY:-}"           # yes/no; blank = ask (node profile) / default no
DNS="${DNS:-1.1.1.1}"

DRYRUN=false
ARGS=("$@"); for a in "${ARGS[@]+"${ARGS[@]}"}"; do [ "$a" = "--dry-run" ] && DRYRUN=true; done
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"

c(){ printf '\033[%sm' "$1"; }
info(){ echo "${C_CYAN}▸${RESET} ${BOLD}$*${RESET}"; }   # every ▸ line is bold (matches bare-metal)
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
detect_public_ip(){ local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"; printf '%s' "$ip"; }
ask_tty(){ local v p="$1" d="${2:-}"   # prompt on the terminal (curl|bash keeps a tty); else use default
  if printf '%s%s: ' "$p" "${d:+ [$d]}" 2>/dev/null >/dev/tty && IFS= read -r v 2>/dev/null </dev/tty; then printf '%s' "${v:-$d}"
  else printf '%s' "$d"; fi; }
ask_yn_tty(){ local v p="$1" d="${2:-n}"   # y/n on the tty -> echoes yes|no (default when blank / no tty)
  v="$(ask_tty "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N'))" "")"
  case "${v:-$d}" in [Yy]*) printf yes;; *) printf no;; esac; }
rand_pw(){ head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16; }

# ── styling shared with the bare-metal installers (same palette + bold ▸ headers) ──
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_GREY=$'\033[90m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_GREY=""; C_CYAN=""; C_RED=""; C_YEL=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
bb(){ printf '%s%s%s%s' "$BOLD" "$C_BLUE" "$*" "$RESET"; }   # bold + blue (handoff URL / login)
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
ask(){ local v p="$1" d="${2:-}"; read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty || v=""; printf -v "$3" '%s' "${v:-$d}"; }
v_ip(){ printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1; local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; }
v_host(){ v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_port(){ case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
port_free(){ have ss || return 0; [ -z "$(ss -lnuH "sport = :$1" 2>/dev/null)" ]; }   # UDP port not already bound
v_freeport(){ v_port "$1" && port_free "$1"; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }
v_email(){   case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }
v_cftoken(){ [ -n "$1" ]; }
v_cforigin(){ [ -n "$1" ]; }
v_cfport(){  case "$1" in 443|2053|2083|2087|2096|8443) return 0;; *) return 1;; esac; }  # ports Cloudflare's proxy forwards (HTTPS)
v_iface(){   case "$1" in ""|*[!a-zA-Z0-9_-]*) return 1;; esac; [ "${#1}" -le 15 ]; }
v_subnet(){  have python3 || return 0; python3 -c "import ipaddress,sys;ipaddress.ip_network(sys.argv[1],strict=False)" "$1" >/dev/null 2>&1; }
v_url(){     case "$1" in ""|*" "*) return 1;; esac
             local h="${1#http://}"; h="${h#https://}"; h="${h%%/*}"; h="${h%%:*}"; v_host "$h"; }
v_httpsurl(){ case "$1" in https://*|http://*) v_host "$(x="${1#http://}"; x="${x#https://}"; x="${x%%/*}"; printf '%s' "${x%%:*}")";; *) return 1;; esac; }
v_token(){   [ -n "$1" ] && [ "${#1}" -ge 8 ]; }
# parse_panel_url <input> -> PANEL_HOST_NOPORT, PANEL_BASE (subpath), URL_PORT  (same logic as bare-metal)
parse_panel_url(){ local u="$1" hostport rest
  u="${u#http://}"; u="${u#https://}"; u="${u%/}"
  hostport="${u%%/*}"; rest="${u#"$hostport"}"
  PANEL_BASE="$rest"; [ "$PANEL_BASE" = "/" ] && PANEL_BASE=""; PANEL_BASE="${PANEL_BASE%/}"
  case "$hostport" in
    *:*) PANEL_HOST_NOPORT="${hostport%%:*}"; URL_PORT="${hostport##*:}";;
    *)   PANEL_HOST_NOPORT="$hostport"; URL_PORT="";;
  esac; }
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi
  while :; do
    if read -rp "$p [$(col "$C_BLUE" "$d")]: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; return; }; done
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts"
    warn "‘$v’ isn't one of: $opts"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return; fi
  while :; do
    if read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’"
    warn "$hint"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }

# ── turn-proxy (vk-turn-proxy) — host systemd service forwarding to the published wg port ──
# The turn-proxy runs as a HOST systemd service (forwards to the node container's published wg
# port). Its record goes into ./data/node, which is bind-mounted into swg-node at
# /var/lib/swg-noded, so swg-noded (SWG_TURN_RECORD) reports the turn-proxies to the panel.
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"; TURN_RECORD="${TURN_RECORD:-$INSTALL_DIR/data/node/turn-proxy.json}"
declare -A TP_LISTEN TP_CONNECT TP_WRAP
turn_repo_owner(){ case "$1" in
  wings) echo "WINGS-N/vk-turn-proxy";; samosvalishe) echo "samosvalishe/vk-turn-proxy";;
  kiper292) echo "kiper292/vk-turn-proxy";; anton48) echo "anton48/vk-turn-proxy";;
  main) echo "cacggghp/vk-turn-proxy";; *) return 1;; esac; }
gen_wrap_key(){ $DRYRUN && { echo "GENERATED-ON-REAL-RUN"; return 0; }
  openssl rand -hex 32 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
turn_wrap_flags(){ local k; case "$1" in   # per-fork obfuscation flags (verified from each binary's -h)
  anton48)      k="$(gen_wrap_key)"; printf -- '-wrap-srtp -wrap-key %s' "$k";;
  samosvalishe) k="$(gen_wrap_key)"; printf -- '-wrap -wrap-key %s' "$k";;
  wings)        k="$(gen_wrap_key)"; printf -- '-wrap-mode on -wrap-key %s' "$k";;
  *) printf '';; esac; }
detect_turn(){ TP_LISTEN=(); TP_CONNECT=(); TP_WRAP=(); local u name exe lis con wk
  for u in /etc/systemd/system/*.service; do [ -e "$u" ] || continue
    exe="$(sed -n 's/^ExecStart=//p' "$u" 2>/dev/null | head -1)"
    case "$exe" in *-listen*-connect*|*-connect*-listen*) ;; *) continue;; esac
    name="$(basename "$u" .service)"
    lis="$(printf '%s\n' "$exe" | sed -n 's/.*-listen[ =]\{1,\}\([^ ]*\).*/\1/p')"
    con="$(printf '%s\n' "$exe" | sed -n 's/.*-connect[ =]\{1,\}\([^ ]*\).*/\1/p')"
    wk="$(printf '%s\n' "$exe" | sed -n 's/.*-wrap-key[ =]\{1,\}\([^ ]*\).*/\1/p')"
    TP_LISTEN[$name]="$lis"; TP_CONNECT[$name]="$con"; TP_WRAP[$name]="$wk"; done; }
turn_latest_tag(){ $DRYRUN && { echo "v0.0.0"; return 0; }
  curl -fsSL --connect-timeout 10 --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
# One instance == one systemd unit, keyed by <fork>-<port> so the SAME fork can run many times
# (2× wings, 3× samosvalishe, …) — each on its own port with its own wrap key.
install_turn_binary(){ local fork="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver port inst
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  port="${listen##*:}"; inst="$fork-$port"; dir="$TURN_DIR/$inst"; bin="$dir/server"; svc="vk-turn-proxy-$inst"
  if [ -e "/etc/systemd/system/$svc.service" ]; then warn "turn-proxy $svc already exists — pick another port"; return 0; fi
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$dir"; info "Installing $owner ($listen → $connect) — downloading the binary from GitHub (up to ~2 min)…"
  if $DRYRUN; then echo "    [skip] curl -fsSL $url -o $bin"
  elif ! { curl -fsSL --connect-timeout 10 --max-time 120 --retry 2 --retry-delay 2 --retry-all-errors "$url" -o "$PREFIX$bin" && chmod +x "$PREFIX$bin"; }; then warn "download failed ($url) — skipping"; return 0; fi
  ver="$(turn_latest_tag "$owner")"
  printf '%s\n' "$owner" | writef "$dir/repo.txt" 644; printf '%s\n' "${ver:-unknown}" | writef "$dir/version.txt" 644
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
  ok "installed turn-proxy $(col "$C_GREEN" "$inst") ($owner ${ver:-?}) — $listen → $connect"; }
install_turn_proxy(){   # <fork> — params, then install (the fork is chosen in choose_turn_proxy)
  local sel="$1" owner pub port connect extra; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "${NODE_ENDPOINT:-$(detect_public_ip)}" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "56000" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local n; for n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$n' — pick another port (enter 'new' again)"; return 0; }; done
  ask_valid "WireGuard/AmneziaWG address it forwards to (ip:port)" "127.0.0.1:${NODE_LISTEN_PORT:-51820}" connect v_hostport "ip:port, e.g. 127.0.0.1:51820"
  local wrap extra; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  ask "Extra server flags (optional)" "" extra
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap${extra:+ $extra}"; }
write_turn_record(){ detect_turn; local json="" sep="" n
  for n in "${!TP_LISTEN[@]}"; do json+="$sep    { \"service\": \"$n\", \"listen\": \"${TP_LISTEN[$n]}\", \"connect\": \"${TP_CONNECT[$n]}\", \"wrap_key\": \"${TP_WRAP[$n]}\" }"; sep=$',\n'; done
  writef "$TURN_RECORD" 640 <<EOF
{
  "turn_proxies": [
$json
  ]
}
EOF
}
choose_turn_proxy(){ info "Checking for turn-proxy servers on this host…"; local sel names n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    echo
    if [ "${#names[@]}" -gt 0 ]; then echo "  Installed turn-proxy servers:"
      for n in "${names[@]}"; do printf '    %s %s\n' "$(col "$C_GREEN" "$n")" "$(b "(${TP_LISTEN[$n]} → ${TP_CONNECT[$n]})")"; done; echo; fi
    echo "  Here is a list of turn-proxy branches available for installation:"; echo
    menu "$(col "$C_BLUE" wings)"        "For Android — https://github.com/WINGS-N/vk-turn-proxy"
    menu "$(col "$C_BLUE" samosvalishe)" "For Android — https://github.com/samosvalishe/vk-turn-proxy"
    menu "$(col "$C_BLUE" kiper292)"     "For Android — https://github.com/kiper292/vk-turn-proxy"
    menu "$(col "$C_BLUE" anton48)"      "For iOS — https://github.com/anton48/vk-turn-proxy"
    printf '  Select a turn-proxy repository to install or just press %s to skip and proceed with the setup: ' "$(b Enter)"
    if ! read -r sel 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    sel="${sel//[[:space:]]/}"; [ -z "$sel" ] && break
    case "$sel" in wings|samosvalishe|kiper292|anton48) install_turn_proxy "$sel"; continue;;
      *) warn "‘$sel’ isn't one of: wings samosvalishe kiper292 anton48 (or press Enter to skip)";; esac
  done; write_turn_record; }

# ───────────────────────── flags ─────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)              PROFILE="${2:-host}"; shift 2 || shift;;
    host|node|host-node)    PROFILE="$1"; shift;;          # bare positional profile (e.g. "docker node")
    -pass|--pass|-password) PANEL_PASSWORD="${2:-}"; shift 2 || shift;;
    -user|--user|-username) PANEL_USER="${2:-}"; shift 2 || shift;;
    -domain|--domain)       PANEL_DOMAIN="${2:-}"; shift 2 || shift;;
    -base|--base)           PANEL_BASE="${2:-}"; shift 2 || shift;;
    -port|--port)           PANEL_PORT="${2:-}"; shift 2 || shift;;
    -tls|--tls)             TLS="${2:-}"; shift 2 || shift;;
    -email|--email)         ACME_EMAIL="${2:-}"; shift 2 || shift;;
    -cf-token|--cf-token)   CF_TOKEN="${2:-}"; shift 2 || shift;;
    -cf-origin|--cf-origin) CF_ORIGIN_TOKEN="${2:-}"; shift 2 || shift;;
    -key|--key|-token)      NODE_TOKEN="${2:-}"; shift 2 || shift;;
    -host|--host|-url)      PANEL_URL="${2:-}"; shift 2 || shift;;
    -endpoint|--endpoint)   NODE_ENDPOINT="${2:-}"; shift 2 || shift;;
    -verify|--verify)       TLS_VERIFY="${2:-}"; shift 2 || shift;;
    -iface|--iface)         NODE_IFACE="${2:-}"; shift 2 || shift;;
    -ifaces|--ifaces)       NODE_IFACES="${2:-}"; shift 2 || shift;;
    --dry-run)              shift;;
    *)                      shift;;
  esac
done
case "$PROFILE" in host|node|host-node) ;; *) die "profile must be host|node|host-node";; esac
[ -n "$PANEL_BASE" ] && PANEL_BASE="/$(printf '%s' "$PANEL_BASE" | sed 's#^/*##; s#/*$##')"

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — .env renders under ./dryrun, no Docker commands run."; rm -rf "$PREFIX"; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ───────────────────────── per-profile requirements ─────────────────────────
# Compose interpolates the whole file (both services), so every referenced var must be
# non-empty even when its service isn't in the active profile — fill sane placeholders.
ask_panel_login(){   # Step 1 — Panel URL (identical look + parsing to bare-metal); login auto-generated
  echo
  echo "$(b 'Step 1. Panel URL')"
  echo
  echo "      Where the panel is reached — an IP, a host, or a host with a subpath to"
  echo "      live under an existing site (e.g. $(b 'vpn.example.com/swg'))."
  echo
  local def="${PANEL_DOMAIN:-$(detect_public_ip)}"; [ -z "$def" ] && def=localhost
  PANEL_DOMAIN=""   # ask_valid skips if non-empty; force the prompt and parse the result
  ask_valid "Enter panel URL (https://…)" "$def" PANEL_DOMAIN v_url "enter a host or IP, optionally with a /subpath (e.g. vpn.example.com/swg)"
  parse_panel_url "$PANEL_DOMAIN"
  PANEL_DOMAIN="$PANEL_HOST_NOPORT"; [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
  [ -n "$PANEL_BASE" ] && ok "panel will be served under subpath ${PANEL_BASE}/"
  PANEL_PORT="${PANEL_PORT:-${URL_PORT:-443}}"   # honor :port from the URL; else default 443 (host-published port)
  [ "${PANEL_USER:-admin}" = admin ] && PANEL_USER="admin$(( RANDOM % 900 + 100 ))"   # admin+3 digits, like bare-metal (-user overrides)
  [ -z "$PANEL_PASSWORD" ] && PANEL_PASSWORD="$(rand_pw)"   # auto-generated; pass -pass to set your own
  return 0   # never let a short-circuited && above make the function (and set -e) fail
}
ask_panel_tls(){     # Step 2 — TLS certificate (same look as bare-metal); issued INSIDE the container by acme.sh
  echo
  echo "$(b 'Step 2. TLS certificate')"
  echo
  menu "$(b "$(col "$C_BLUE" 'letsencrypt (default)')")" "Let's Encrypt cert via acme.sh HTTP-01 (publish port 80: -p 80:80)"
  menu "$(col "$C_BLUE" cloudflare)"                    "Let's Encrypt cert, validated via Cloudflare DNS-01 (no port 80) — needs a Zone:DNS:Edit+Read token + email"
  menu "$(col "$C_BLUE" cf15)"                          "Cloudflare Origin certificate, 15 years — ONLY valid behind Cloudflare's proxy (orange cloud); needs an API token (Zone → SSL and Certificates → Edit)"
  menu "$(col "$C_BLUE" selfsigned)"                    "OK for testing"
  menu "$(col "$C_GREY" none)"                          "plain HTTP — only behind a tunnel/reverse-proxy that terminates TLS"
  ask_choice "Select TLS certificate" "letsencrypt" TLS "letsencrypt cloudflare cf15 selfsigned none"
  case "$TLS" in letsencrypt|cloudflare|cf15)
    case "$PANEL_DOMAIN" in *[a-zA-Z]*) : ;; *) die "TLS=$TLS needs a domain (FQDN), not '$PANEL_DOMAIN' — re-run and pick selfsigned for an IP";; esac
    case "$PANEL_DOMAIN" in *.*) : ;; *) die "TLS=$TLS needs a domain (FQDN), not '$PANEL_DOMAIN' — re-run and pick selfsigned for an IP";; esac ;;
  esac
  case "$TLS" in
    letsencrypt) ask_valid "ACME account email" "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com"
                 warn "letsencrypt validates over HTTP-01 — publish port 80 to the panel container (compose maps 80:80)";;
    cloudflare)  ask_valid "Cloudflare API token (needs Zone:DNS:Edit + Zone:Read)" "$CF_TOKEN" CF_TOKEN v_cftoken "the API token can't be empty"
                 ask_valid "ACME account email" "$ACME_EMAIL" ACME_EMAIL v_email "enter a valid email, e.g. you@example.com";;
    cf15)        warn "cf15 issues a Cloudflare Origin cert — it is ONLY trusted behind Cloudflare's proxy (orange cloud)."
                 if ! v_cfport "$PANEL_PORT"; then
                   warn "port $(col "$C_YEL" "$PANEL_PORT") is NOT one Cloudflare's proxy forwards (only 443, 2053, 2083, 2087, 2096, 8443) —"
                   warn "the panel would be unreachable through the orange cloud. Use one of those ports (or Cloudflare Spectrum), or grey-cloud the record and accept an untrusted direct cert."
                 fi
                 ask_valid "Cloudflare API token (Zone → SSL and Certificates → Edit)" "$CF_ORIGIN_TOKEN" CF_ORIGIN_TOKEN v_cforigin "paste an API token — the legacy Origin CA Key is deprecated (sunset 2026-09-30)";;
  esac
  return 0
}
ask_node_conn(){     # NODE SETUP — panel connection + endpoint, styled like bare-metal install-node.sh
  # Panel connection — normally supplied by the install command's -host / -key flags.
  ask_valid "Panel URL (https://host[/subpath])" "$PANEL_URL" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"
  ask_valid "Node enrollment key (from the Nodes screen)" "$NODE_TOKEN" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"
  case "$PANEL_URL" in https://*) ;; *) warn "panel URL is not https:// — the key would travel in clear. Continue only if you know why.";; esac
  [ -z "$TLS_VERIFY" ] && TLS_VERIFY="$(ask_yn_tty "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" n)"
  echo
  echo "$(b 'Step 1. Endpoint IP clients dial for this node')"
  echo
  ask_valid "Endpoint IP clients dial for this node" "${NODE_ENDPOINT:-$(detect_public_ip)}" NODE_ENDPOINT v_host "enter an IP address or hostname"
  return 0
}
ask_node_iface(){    # Step 2 — WG/AWG interface (container-managed); mirrors bare-metal's single-interface prompts
  echo
  echo "$(b 'Step 2. WireGuard / AmneziaWG setup')"
  echo
  echo "      The interface is brought up INSIDE the swg-node container from these values."
  echo "      Need several interfaces or custom AmneziaWG obfuscation? set $(b NODE_IFACES) in"
  echo "      $INSTALL_DIR/.env, or mount $(b /etc/swg-node/*.conf) (see docs/DOCKER.md)."
  echo
  local _proto def_if d_if d_port d_addr
  d_if="$NODE_IFACE"; d_port="$NODE_LISTEN_PORT"; d_addr="$NODE_ADDRESS"
  ask_choice "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) NODE_PLAIN_WG=yes; def_if=wg0;; *) NODE_PLAIN_WG=no; def_if=awg0;; esac
  case "$d_if" in ""|awg0|wg0) d_if="$def_if";; esac        # default name follows the protocol
  NODE_IFACE="";       ask_valid "Interface name" "$d_if" NODE_IFACE v_iface "1–15 chars: letters, digits, - or _"
  NODE_LISTEN_PORT=""; ask_valid "Listen port" "$d_port" NODE_LISTEN_PORT v_freeport "port 1–65535 and free (not already in use)"
  NODE_ADDRESS="";     ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$d_addr" NODE_ADDRESS v_subnet "enter a CIDR, e.g. 10.8.0.0/24"
  return 0
}
case "$PROFILE" in
  host)
    echo; info "PANEL SETUP"
    ask_panel_login; ask_panel_tls
    NODE_TOKEN="${NODE_TOKEN:-set-in-nodes-screen}"; PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"; NODE_ENDPOINT="${NODE_ENDPOINT:-127.0.0.1}"
    ;;
  host-node)
    echo; info "PANEL SETUP"
    ask_panel_login; ask_panel_tls
    PANEL_URL="https://swg-panel:8443"   # the local node reaches the panel on the compose network
    TLS_VERIFY="${TLS_VERIFY:-no}"        # local node → local panel is self-signed on the compose net
    echo; info "NODE SETUP"
    ask_valid "Node enrollment key (from the Nodes screen)" "$NODE_TOKEN" NODE_TOKEN v_token "bring up 'docker host' first, add the node, then re-run as host-node with this key"
    echo
    echo "$(b 'Step 1. Endpoint IP clients dial for this node')"
    echo
    ask_valid "Endpoint IP clients dial for this node" "${NODE_ENDPOINT:-$(detect_public_ip)}" NODE_ENDPOINT v_host "enter an IP address or hostname"
    ask_node_iface
    ;;
  node)
    echo; info "NODE SETUP"
    ask_node_conn
    ask_node_iface
    PANEL_PASSWORD="${PANEL_PASSWORD:-unused-on-node-only}"; PANEL_DOMAIN="${PANEL_DOMAIN:-localhost}"
    ;;
esac
TLS="${TLS:-selfsigned}"         # concrete value for .env (node profile never prompts for it)
TLS_VERIFY="${TLS_VERIFY:-no}"   # concrete value for .env (host profile leaves it unset)

# ───────────────────────── ensure Docker ─────────────────────────
info "Docker"
if ! have docker; then
  info "installing Docker (get.docker.com)"; run sh -c "curl -fsSL https://get.docker.com | sh"
fi
if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif have docker-compose; then COMPOSE="docker-compose"
else COMPOSE="docker compose"; $DRYRUN || warn "docker compose plugin not detected — install it if 'up' fails"; fi

# ───────────────────────── stage project ─────────────────────────
info "Staging project in $INSTALL_DIR"
mkdir -p "$PREFIX$INSTALL_DIR"
for f in docker-compose.yml Dockerfile Dockerfile.node .dockerignore VERSION \
         swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
  [ -e "$SRC/$f" ] && cp -a "$SRC/$f" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
done
[ -d "$SRC/vendor" ] && cp -a "$SRC/vendor" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
[ -d "$SRC/docker" ] && cp -a "$SRC/docker" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
ok "staged build context"

# ───────────────────────── write .env ─────────────────────────
mkdir -p "$PREFIX$INSTALL_DIR"
cat > "$PREFIX$INSTALL_DIR/.env" <<EOF
# generated by install-docker.sh — profile: $PROFILE
# ───────── Panel (profiles: host, host-node) ─────────
PANEL_PASSWORD=$PANEL_PASSWORD
PANEL_USER=$PANEL_USER
PANEL_DOMAIN=$PANEL_DOMAIN
PANEL_BASE=$PANEL_BASE
TLS=$TLS
ACME_EMAIL=$ACME_EMAIL
CF_TOKEN=$CF_TOKEN
CF_ORIGIN_TOKEN=$CF_ORIGIN_TOKEN
PANEL_PORT=$PANEL_PORT

# ───────── Node (profiles: node, host-node) ─────────
PANEL_URL=$PANEL_URL
NODE_TOKEN=$NODE_TOKEN
NODE_ENDPOINT=$NODE_ENDPOINT
NODE_IFACE=$NODE_IFACE
NODE_IFACES=$NODE_IFACES
NODE_LISTEN_PORT=$NODE_LISTEN_PORT
NODE_ADDRESS=$NODE_ADDRESS
NODE_MTU=$NODE_MTU
NODE_PLAIN_WG=$NODE_PLAIN_WG
TLS_VERIFY=$TLS_VERIFY
DNS=$DNS
EOF
chmod 600 "$PREFIX$INSTALL_DIR/.env" 2>/dev/null || true
ok "wrote $INSTALL_DIR/.env (profile $PROFILE)"

# ── reset the panel login on every install (matches bare-metal) ────────────────
# The container writes data/etc/auth only when it is MISSING, so a reused data dir would
# otherwise keep the OLD login. Drop any existing auth and --force-recreate, so the entrypoint
# rewrites it from the freshly-generated .env credentials printed below. (Node has no login.)
RECREATE=""
if [ "$PROFILE" != node ]; then
  $DRYRUN || rm -f "$PREFIX$INSTALL_DIR/data/etc/auth"
  RECREATE="--force-recreate"
fi

# ───────────────────────── bring it up ─────────────────────────
info "Starting compose profile '$PROFILE'"
# Default compose pulls prebuilt images from GHCR (pull_policy: missing). If you switch
# docker-compose.yml back to building from source, re-run with: $COMPOSE … up -d --build
if $DRYRUN; then echo "    [skip] (cd $INSTALL_DIR && $COMPOSE --profile $PROFILE up -d $RECREATE)"
else ( cd "$INSTALL_DIR" && $COMPOSE --profile "$PROFILE" up -d $RECREATE ); fi

# ───────────────────────── turn-proxy (node-bearing profiles) ─────────────────────────
# Runs on the HOST (systemd) and forwards to the wg UDP port the swg-node container publishes.
if [ "$PROFILE" = node ] || [ "$PROFILE" = host-node ]; then
  echo; echo "$(b 'Step 3. TURN-PROXY setup') (https://github.com/cacggghp/vk-turn-proxy)"; echo
  choose_turn_proxy
fi

# ───────────────────────── SUMMARY ─────────────────────────
echo; ok "Docker install complete (profile: $PROFILE)."
echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
case "$PROFILE" in host|host-node)
  SCH=https; [ "$TLS" = none ] && SCH=http
  PORTSUF=":${PANEL_PORT}"; if { [ "$SCH" = https ] && [ "$PANEL_PORT" = 443 ]; } || { [ "$SCH" = http ] && [ "$PANEL_PORT" = 80 ]; }; then PORTSUF=""; fi
  echo "  Panel     $(bb "${SCH}://${PANEL_DOMAIN}${PORTSUF}${PANEL_BASE}/")"
  echo "  Login     $(bb "$PANEL_USER") / $(bb "$PANEL_PASSWORD")   (change later in the panel → Account)"
  echo "  TLS       $(b "$TLS")  ·  host port $(b "$PANEL_PORT")" ;;
esac
case "$PROFILE" in node|host-node)
  echo "  Node      → syncs to $(bb "$PANEL_URL")   ·  endpoint $(bb "$NODE_ENDPOINT")"
  echo; echo "  $(b 'Interface') (in the swg-node container):"
  if [ -n "$NODE_IFACES" ]; then IFS=',' read -ra _ifs <<< "$NODE_IFACES"
    for e in "${_ifs[@]}"; do IFS=':' read -r _nm _pt _ad _pr <<< "$e"
      printf '    %s %-9s endpoint %s  subnet %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$_nm")")" "${_pr:-amneziawg}" "$(bb "$NODE_ENDPOINT:$_pt")" "$(b "$_ad")"; done
  else _pr=amneziawg; [ "$NODE_PLAIN_WG" = yes ] && _pr=wireguard
    printf '    %s %-9s endpoint %s  subnet %s  mtu %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$NODE_IFACE")")" "$_pr" "$(bb "$NODE_ENDPOINT:$NODE_LISTEN_PORT")" "$(b "$NODE_ADDRESS")" "$(b "$NODE_MTU")"
  fi
  detect_turn 2>/dev/null || true
  if [ "${#TP_LISTEN[@]}" -gt 0 ]; then echo; echo "  $(b 'Turn-proxy') instances (host services → the node container):"
    for n in "${!TP_LISTEN[@]}"; do wk="${TP_WRAP[$n]}"
      printf '    %s %s → %s   %s\n' "$(col "$C_GREEN" "$(printf '%-22s' "$n")")" "$(bb "${TP_LISTEN[$n]}")" "$(b "${TP_CONNECT[$n]}")" "${wk:+wrap-key $(b "$wk")}"; done
  fi ;;
esac
echo
echo "  Dir       $(b "$INSTALL_DIR")  ·  edit $(b .env), then $(b "$COMPOSE --profile $PROFILE up -d")"
echo "  Logs      $(b "cd $INSTALL_DIR && $COMPOSE logs -f")"
case "$PROFILE" in host|host-node) echo "  Next      add entry servers in the panel: $(b 'Nodes → Add node')";; esac
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun$INSTALL_DIR/.env"; }
