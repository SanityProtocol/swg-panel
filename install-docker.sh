#!/usr/bin/env bash
# install-docker.sh — one-line Docker installer for swg-panel.
#
#   Panel (host):      … | sudo bash -s docker host   -pass SECRET -domain panel.example.net
#   Node only:         … | sudo bash -s docker node   -key KEY -host https://panel.example.net -endpoint 203.0.113.7
#
# `docker host` is the panel entry point: Step 1 asks the role — master or host — exactly
# like bare-metal (install-host.sh):
#   master  panel + this box also runs WG/AWG (a co-located node container), auto-enrolled
#           in ONE pass — no "add the node in the panel first". (compose profile: master)
#   host    panel only; WG/AWG nodes are deployed separately with `docker node` (the panel's
#           Nodes → Add node screen prints the command). (compose profile: host)
# `docker node` is the entry point for a separate node box. Pass -role master|host to skip
# the Step 1 prompt; the bare word `master` also forces the master role.
#
# Ensures Docker is present, stages the project under /opt/swg-panel-docker, writes a
# .env, and brings up the chosen compose profile. Run as root. --dry-run renders the
# .env under ./dryrun and runs no Docker commands.
#
#   -role master|host               role for the `host` entry (skips the Step 1 prompt)
#   --profile host|node|master      pick the compose profile directly (host-node = master alias)
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
ROLE="${ROLE:-}"                        # master | host — asked in Step 1 when the entry is `host`.
                                        # master ⇒ master compose profile (panel + a co-located,
                                        # auto-enrolled node container); mirrors bare-metal master.
BUILD="${BUILD:-false}"                 # true = build images from source (stages full context); default pulls from GHCR
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
NODE_NAME="${NODE_NAME:-}"             # local node's name in the panel (master); blank = this host's hostname
NODE_COLOR="${NODE_COLOR:-#34d399}"   # local node's swatch in the panel (master); bare-metal's first palette colour
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
  local sel="$1" owner pub port connect; owner="$(turn_repo_owner "$sel")" || { warn "unknown turn-proxy branch: $sel"; return 0; }
  ask_valid "Public IP this turn-proxy is reached at" "${NODE_ENDPOINT:-$(detect_public_ip)}" pub v_host "an IP or hostname"
  echo
  ask_valid "Turn-proxy listen port" "56000" port v_freeport "port 1–65535 and free (not already in use)"
  detect_turn; local n; for n in "${!TP_LISTEN[@]}"; do [ "${TP_LISTEN[$n]##*:}" = "$port" ] && { warn "port $port is already used by turn-proxy '$n' — pick another port (enter 'new' again)"; return 0; }; done
  local defport="${NODE_LISTEN_PORT:-51820}" _e _nm _pt _pr label clabel pad _ifs
  echo
  echo "  Available wg/awg interfaces:"
  if [ -n "$NODE_IFACES" ]; then
    IFS=',' read -ra _ifs <<< "$NODE_IFACES"
    defport="$(printf '%s' "${_ifs[0]}" | cut -d: -f2)"
    for _e in "${_ifs[@]}"; do
      _nm="$(printf '%s' "$_e"|cut -d: -f1)"; _pt="$(printf '%s' "$_e"|cut -d: -f2)"; _pr="$(printf '%s' "$_e"|cut -d: -f4)"
      [ "$_pr" = wg ] && _pr=wg || _pr=awg
      label="$_nm on $_pr"; clabel="$(col "$C_GREEN" "$_nm") on $(b "$_pr")"
      pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
      printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$_pt")"
    done
  else
    _pr=awg; [ "${NODE_PLAIN_WG:-}" = yes ] && _pr=wg
    label="$NODE_IFACE on $_pr"; clabel="$(col "$C_GREEN" "$NODE_IFACE") on $(b "$_pr")"
    pad=$((15 - ${#label})); [ "$pad" -lt 1 ] && pad=1
    printf '    %s%*s%s\n' "$clabel" "$pad" "" "$(col "$C_BLUE" "127.0.0.1:$defport")"
  fi
  echo
  ask_valid "WireGuard/AmneziaWG address it forwards to (ip:port)" "127.0.0.1:${defport}" connect v_hostport "ip:port, e.g. 127.0.0.1:51820"
  echo
  local wrap; wrap="$(turn_wrap_flags "$sel")"
  [ -n "$wrap" ] && info "Obfuscation: a 64-hex wrap key is generated, baked into the unit, and recorded for the panel / client configs." \
                 || warn "$sel has no wrap/srtp obfuscation flags — installing plain (-listen/-connect only)."
  install_turn_binary "$sel" "$owner" "$pub:$port" "$connect" "$wrap"; }
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
      for n in "${names[@]}"; do printf '    %s %s\n' "$(col "$C_GREEN" "$n")" "$(b "(${TP_LISTEN[$n]} → ${TP_CONNECT[$n]})")"; done
    else warn "No turn-proxy servers found on this box."; fi
    echo
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
    master)                 PROFILE=master; ROLE=master; shift;; # bare-metal-style role word → master profile
    host|node|host-node)    PROFILE="$1"; shift;;          # bare positional profile (e.g. "docker node")
    -role|--role)           ROLE="${2:-}"; shift 2 || shift;;    # master|host — skips the Step 1 role prompt
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
    --build)                BUILD=true; shift;;
    --dry-run)              shift;;
    *)                      shift;;
  esac
done
case "$PROFILE" in host|node|host-node|master) ;; *) die "profile must be host|node|master";; esac
[ "$PROFILE" = host-node ] && PROFILE=master                    # normalize the legacy alias
[ "$PROFILE" = master ] && ROLE=master                          # explicit master profile ⇒ master role
case "$ROLE" in ""|master|host) ;; *) die "role must be master|host";; esac
[ -n "$PANEL_BASE" ] && PANEL_BASE="/$(printf '%s' "$PANEL_BASE" | sed 's#^/*##; s#/*$##')"

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — .env renders under ./dryrun, no Docker commands run."; rm -rf "$PREFIX"; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Idempotent re-install: re-use the current .env's values (token, URL, login, interface defaults) so
# re-running keeps everything and the ./data state is untouched. To start fresh, run the uninstaller.
EXISTING_DOCKER=no
if [ -f "$INSTALL_DIR/.env" ]; then
  EXISTING_DOCKER=yes
  for _k in PANEL_URL NODE_TOKEN NODE_ENDPOINT PANEL_USER PANEL_PASSWORD PANEL_DOMAIN PANEL_PORT \
            PANEL_BASE NODE_IFACE NODE_IFACES NODE_LISTEN_PORT NODE_ADDRESS NODE_MTU NODE_PLAIN_WG DNS TLS_VERIFY; do
    [ -n "${!_k:-}" ] && continue                       # an explicit flag/env wins over the stored value
    _v="$(sed -n "s/^${_k}=//p" "$INSTALL_DIR/.env" 2>/dev/null | head -1)"
    _v="${_v%\"}"; _v="${_v#\"}"                        # strip surrounding quotes
    [ -n "$_v" ] && printf -v "$_k" '%s' "$_v"
  done
  info "Existing docker install detected in $INSTALL_DIR — keeping your .env + ./data (token, login, interfaces). To start fresh, uninstall first."
fi

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
  local def="${PANEL_DOMAIN:-$(detect_public_ip)}"; [ -z "$def" ] && def=localhost; local _url_ans
  PANEL_DOMAIN=""   # ask_valid skips if non-empty; force the prompt and parse the result
  ask_valid "Enter panel URL (https://…)" "$def" PANEL_DOMAIN v_url "enter a host or IP, optionally with a /subpath (e.g. vpn.example.com/swg)"
  while :; do
    parse_panel_url "$PANEL_DOMAIN"
    { [ -z "$URL_PORT" ] || v_cfport "$URL_PORT"; } && break   # no port or a Cloudflare-proxyable one → fine
    echo
    warn "Port $(col "$C_YEL" "$URL_PORT") is NOT a standard HTTPS port Cloudflare's proxy (orange cloud) forwards."
    echo "         Cloudflare proxies HTTPS only on: $(b '443, 2053, 2083, 2087, 2096, 8443')."
    echo "         Behind the orange cloud the panel on $URL_PORT is unreachable, so $(b cloudflare)/$(b cf15)"
    echo "         certificates won't work. ($(b letsencrypt)/$(b selfsigned) on a directly-reachable port is fine.)"
    echo
    printf '  To keep the port %s type %s, or enter a new URL to change: ' "$URL_PORT" "$(bb proceed)"
    read -r _url_ans </dev/tty || _url_ans=proceed
    case "$(printf '%s' "$_url_ans" | tr -d '[:space:]')" in
      proceed|"") break;;                                           # keep the current port
      *) if v_url "$_url_ans"; then PANEL_DOMAIN="$_url_ans"        # adopt the new URL; loop re-parses + re-checks
         else warn "‘$_url_ans’ isn't a valid host/URL — try again."; fi ;;
    esac
  done
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
ask_node_conn(){     # NODE SETUP — panel connection (endpoint moved into the per-interface wg/awg step)
  # Panel connection — normally supplied by the install command's -host / -key flags.
  ask_valid "Panel URL (https://host[/subpath])" "$PANEL_URL" PANEL_URL v_httpsurl "enter the panel's https:// URL (pass -host to skip this)"
  ask_valid "Node enrollment key (from the Nodes screen)" "$NODE_TOKEN" NODE_TOKEN v_token "paste the key from Nodes → Add node (pass -key to skip this)"
  case "$PANEL_URL" in https://*) ;; *) warn "panel URL is not https:// — the key would travel in clear. Continue only if you know why.";; esac
  [ -z "$TLS_VERIFY" ] && TLS_VERIFY="$(ask_yn_tty "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" n)"
  return 0
}
ask_node_iface(){    # Step 1 — WG/AWG interface (container-managed) + its endpoint; mirrors bare-metal
  echo
  echo "$(b 'Step 1. WireGuard / AmneziaWG setup')   (this interface has its own endpoint IP)"
  echo
  echo "      The interface is brought up INSIDE the swg-node container from these values."
  echo "      Need several interfaces (each with its own endpoint) or custom AmneziaWG obfuscation?"
  echo "      set $(b NODE_IFACES) in $INSTALL_DIR/.env, or mount $(b /etc/swg-node/*.conf) (see $INSTALL_DIR/docker-compose.yml)."
  echo
  local _proto def_if d_if d_port d_addr d_ep
  d_if="$NODE_IFACE"; d_port="$NODE_LISTEN_PORT"; d_addr="$NODE_ADDRESS"; d_ep="${NODE_ENDPOINT:-$(detect_public_ip)}"
  ask_choice "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto "a w awg wg amneziawg wireguard"
  case "$_proto" in w|wg|wireguard) NODE_PLAIN_WG=yes; def_if=wg0;; *) NODE_PLAIN_WG=no; def_if=awg0;; esac
  case "$d_if" in ""|awg0|wg0) d_if="$def_if";; esac        # default name follows the protocol
  NODE_IFACE="";       ask_valid "Interface name" "$d_if" NODE_IFACE v_iface "1–15 chars: letters, digits, - or _"
  NODE_LISTEN_PORT=""; ask_valid "Listen port" "$d_port" NODE_LISTEN_PORT v_freeport "port 1–65535 and free (not already in use)"
  NODE_ADDRESS="";     ask_valid "Tunnel subnet (CIDR; server takes the first host)" "$d_addr" NODE_ADDRESS v_subnet "enter a CIDR, e.g. 10.8.0.0/24"
  NODE_ENDPOINT="";    ask_valid "Endpoint clients dial for $(col "$C_GREEN" "$NODE_IFACE") (this interface's public IP/host)" "$d_ep" NODE_ENDPOINT v_host "enter an IP address or hostname"
  return 0
}
ask_role(){          # Step 1 (panel entry) — master (panel + local node) or host (panel only); mirrors bare-metal
  echo
  echo "$(b 'Step 1. Server role')"
  echo
  menu "$(b "$(col "$C_BLUE" 'master (default)')")" "Panel + this box also runs WG/AWG interfaces — a co-located, auto-enrolled node container"
  menu "$(col "$C_BLUE" host)"                       "Panel only; WG/AWG nodes are deployed separately (run their command from the panel)"
  ask_choice "Select role" "master" ROLE "master host"
}
case "$PROFILE" in
  host|master)
    [ -n "$ROLE" ] || ask_role
    [ "$ROLE" = master ] && PROFILE=master || PROFILE=host
    echo; info "PANEL SETUP"
    ask_panel_login; ask_panel_tls
    if [ "$PROFILE" = master ]; then
      PANEL_URL="https://swg-panel:8443"   # the local node reaches the panel on the compose network
      TLS_VERIFY="${TLS_VERIFY:-no}"        # local node → local panel is self-signed on the compose net
      echo; info "NODE SETUP"
      ask_node_iface
      # single-pass auto-enroll (mirrors bare-metal master): mint the local node's token NOW so it
      # flows into .env below; its pbkdf2 hash + nodes.json entry are written just before compose up.
      [ -n "$NODE_NAME" ]  || NODE_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo node)"
      [ -n "$NODE_TOKEN" ] || NODE_TOKEN="$(head -c18 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')"
      AUTOENROLL=yes
    else
      NODE_TOKEN="${NODE_TOKEN:-set-in-nodes-screen}"; PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"; NODE_ENDPOINT="${NODE_ENDPOINT:-127.0.0.1}"
    fi
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
# Default pulls prebuilt images from GHCR, so only the compose file is needed on the host
# (.env is written below, data/ is created by compose). --build also stages the full build
# context and flips the compose file to build-from-source.
info "Staging project in $INSTALL_DIR"
mkdir -p "$PREFIX$INSTALL_DIR"
cp -a "$SRC/docker-compose.yml" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
if $BUILD; then
  for f in Dockerfile Dockerfile.node Dockerfile.turn .dockerignore VERSION \
           swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
    [ -e "$SRC/$f" ] && cp -a "$SRC/$f" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  done
  [ -d "$SRC/vendor" ] && cp -a "$SRC/vendor" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  [ -d "$SRC/docker" ] && cp -a "$SRC/docker" "$PREFIX$INSTALL_DIR/" 2>/dev/null || true
  # flip compose: comment the GHCR image: lines, uncomment the build: blocks
  sed -i -E 's@^( *)image: (ghcr.io/[^:]*/swg-(panel|node):latest)@\1# image: \2@; s@^( *)# build: \.@\1build: .@; s@^( *)# (build:)$@\1\2@; s@^( *)#   (context: \.)@\1  \2@; s@^( *)#   (dockerfile: Dockerfile.node)@\1  \2@' "$PREFIX$INSTALL_DIR/docker-compose.yml"
  ok "staged full build context (--build: images built from source)"
else
  ok "staged compose file (images pulled prebuilt from GHCR — no build context needed)"
fi

# Standalone node → host networking: every interface port (incl. ones created from the panel) is on
# the host with no publishing, like bare-metal. Not for master (the node needs the swg-panel docker
# DNS). host net disallows per-container `ports:`/`sysctls:`, so disable them + set ip_forward on the host.
if [ "$PROFILE" = node ]; then
  if $DRYRUN; then echo "    [skip] enable host networking for the node service + host ip_forward"
  else
    python3 - "$PREFIX$INSTALL_DIR/docker-compose.yml" <<'PYHOST'
import sys, re
p = sys.argv[1]; lines = open(p).read().splitlines(); out = []; in_node = False
for ln in lines:
    if re.match(r'^  swg-node:\s*$', ln): in_node = True
    elif in_node and re.match(r'^  \S', ln): in_node = False
    if in_node:
        if re.match(r'^    container_name: swg-node\s*$', ln):
            out += [ln, '    network_mode: host        # standalone node: every interface port is on the host']; continue
        if re.match(r'^    (ports|sysctls):\s*$', ln):
            out.append('    # ' + ln.strip() + '   (disabled — host networking)'); continue
        if re.match(r'^      - ("?\$\{NODE_LISTEN_PORT|net\.ipv4\.ip_forward)', ln):
            out.append('    #   ' + ln.strip()); continue
    out.append(ln)
open(p, 'w').write('\n'.join(out) + '\n')
PYHOST
    printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/99-swg-node.conf 2>/dev/null || true
    sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
    ok "node: host networking enabled (every interface port reachable, no per-port publishing)"
  fi
fi

# ───────────────────────── write .env ─────────────────────────
mkdir -p "$PREFIX$INSTALL_DIR"
cat > "$PREFIX$INSTALL_DIR/.env" <<EOF
# generated by install-docker.sh — profile: $PROFILE
# ───────── Panel (profiles: host, master) ─────────
PANEL_PASSWORD=$PANEL_PASSWORD
PANEL_USER=$PANEL_USER
PANEL_DOMAIN=$PANEL_DOMAIN
PANEL_BASE=$PANEL_BASE
TLS=$TLS
ACME_EMAIL=$ACME_EMAIL
CF_TOKEN=$CF_TOKEN
CF_ORIGIN_TOKEN=$CF_ORIGIN_TOKEN
PANEL_PORT=$PANEL_PORT

# ───────── Node (profiles: node, master) ─────────
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

# ── reset login + cert on every install (matches bare-metal) ───────────────────
# The entrypoint only writes data/etc/auth and data/etc/tls/* when they're MISSING, so a reused
# data dir keeps the OLD login AND an OLD cert (e.g. a self-signed left by a previously-failed
# letsencrypt run, which then gets served instead of the TLS mode you just picked → Cloudflare 526).
# Drop both and --force-recreate so the entrypoint re-applies the freshly-chosen login + TLS mode.
# (acme state in data/etc/acme is kept, so letsencrypt/cloudflare reuse their cached cert.)
RECREATE=""
if [ "$PROFILE" != node ]; then
  $DRYRUN || rm -f "$PREFIX$INSTALL_DIR/data/etc/auth" \
                   "$PREFIX$INSTALL_DIR/data/etc/tls/fullchain.pem" "$PREFIX$INSTALL_DIR/data/etc/tls/key.pem"
  RECREATE="--force-recreate"
fi

# ── master: auto-enroll the local node in ONE pass (mirrors bare-metal master) ──
# Write the node into ./data/lib/nodes.json BEFORE compose up. The panel entrypoint only seeds
# an empty {} when nodes.json is MISSING, so this pre-written file wins; the node container gets
# the matching raw token via NODE_TOKEN (.env). No "add the node in the panel first" round-trip.
# Merge into any existing nodes.json so a reinstall keeps other (remote) nodes intact.
if [ "${AUTOENROLL:-}" = yes ] && ! $DRYRUN; then
  ndir="$PREFIX$INSTALL_DIR/data/lib"; mkdir -p "$ndir"
  if python3 - "$ndir/nodes.json" "$NODE_NAME" "$NODE_TOKEN" "$NODE_COLOR" <<'PY'
import sys, os, json, hashlib, base64
path, name, token, color = sys.argv[1:5]
salt = os.urandom(16)
h = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, 200000)
th = "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()
try:
    nodes = json.load(open(path))
    assert isinstance(nodes, dict)
except Exception:
    nodes = {}
nodes[name] = {"name": name, "color": color, "endpoint_host": "",
               "stats_file": "stats-%s.json" % name, "token_hash": th, "created": 0}
json.dump(nodes, open(path, "w"), indent=2)
PY
  then chmod 600 "$ndir/nodes.json" 2>/dev/null || true
       ok "auto-enrolled local node $(col "$C_GREEN" "$NODE_NAME") (single-pass master — no key to paste)"
  else warn "couldn't pre-write nodes.json — add the node in the panel (Nodes → Add node) and set NODE_TOKEN in .env"; fi
fi

# ───────────────────────── bring it up ─────────────────────────
info "Starting compose profile '$PROFILE'$($BUILD && echo ' (building from source)')"
BUILDFLAG=""; $BUILD && BUILDFLAG=--build   # default pulls prebuilt images from GHCR
if $DRYRUN; then echo "    [skip] (cd $INSTALL_DIR && $COMPOSE --profile $PROFILE up -d $RECREATE $BUILDFLAG)"
else ( cd "$INSTALL_DIR" && $COMPOSE --profile "$PROFILE" up -d $RECREATE $BUILDFLAG ); fi

# ── surface the cert outcome (don't let a silent self-signed fallback hide as a Cloudflare 526) ──
if [ "$PROFILE" != node ] && [ "$TLS" != none ] && ! $DRYRUN && have openssl; then
  iss=""; for _i in 1 2 3 4 5 6; do
    # NB: '|| true' — a failed openssl pipeline must NOT abort the script under set -o pipefail
    iss="$(echo | openssl s_client -connect "127.0.0.1:$PANEL_PORT" -servername "$PANEL_DOMAIN" 2>/dev/null | openssl x509 -noout -issuer 2>/dev/null || true)"
    [ -n "$iss" ] && break; sleep 2 || true
  done
  case "$iss" in
    *"CN=$PANEL_DOMAIN"|*"CN = $PANEL_DOMAIN")   # issuer == the domain ⇒ self-signed
      [ "$TLS" = selfsigned ] || {
        warn "TLS=$(b "$TLS") was selected, but the panel is serving a $(b 'SELF-SIGNED') cert — issuance failed and fell back."
        echo "         See why: $(b "$COMPOSE -f $INSTALL_DIR/docker-compose.yml logs swg-panel | grep -i cert")"
        echo "         letsencrypt needs :80 reachable (breaks behind Cloudflare); behind the orange cloud use"
        echo "         $(b cloudflare) (DNS-01) or $(b cf15), and set Cloudflare SSL/TLS to $(b 'Full (strict)')."
      } ;;
    "") : ;;   # couldn't read it (port not up yet) — skip
    *) ok "panel is serving a real certificate (issuer:${iss#*=})" ;;
  esac
fi

# ───────────────────────── turn-proxy (node-bearing profiles) ─────────────────────────
# Runs on the HOST (systemd) and forwards to the wg UDP port the swg-node container publishes.
if [ "$PROFILE" = node ] || [ "$PROFILE" = master ]; then
  echo; echo "$(b 'Step 2. TURN-PROXY setup') (https://github.com/cacggghp/vk-turn-proxy)"; echo
  choose_turn_proxy
fi

# ───────────────────────── SUMMARY ─────────────────────────
echo; ok "Docker install complete (profile: $PROFILE)."
echo; echo "$(b '──────────────── SUMMARY ────────────────')"; echo
case "$PROFILE" in host|master)
  SCH=https; [ "$TLS" = none ] && SCH=http
  PORTSUF=":${PANEL_PORT}"; if { [ "$SCH" = https ] && [ "$PANEL_PORT" = 443 ]; } || { [ "$SCH" = http ] && [ "$PANEL_PORT" = 80 ]; }; then PORTSUF=""; fi
  echo "  Panel     $(bb "${SCH}://${PANEL_DOMAIN}${PORTSUF}${PANEL_BASE}/")"
  echo "  Login     $(bb "$PANEL_USER") / $(bb "$PANEL_PASSWORD")   (change later in the panel → Account)"
  echo "  TLS       $(b "$TLS")  ·  host port $(b "$PANEL_PORT")" ;;
esac
case "$PROFILE" in node|master)
  echo "  Node      → syncs to $(bb "$PANEL_URL")   ·  endpoint $(bb "$NODE_ENDPOINT")"
  echo; echo "  $(b 'Interface') (in the swg-node container):"
  if [ -n "$NODE_IFACES" ]; then IFS=',' read -ra _ifs <<< "$NODE_IFACES"
    for e in "${_ifs[@]}"; do IFS=':' read -r _nm _pt _ad _pr _ep <<< "$e"
      printf '    %s %-9s endpoint %s  subnet %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$_nm")")" "${_pr:-amneziawg}" "$(bb "${_ep:-$NODE_ENDPOINT}:$_pt")" "$(b "$_ad")"; done
  else _pr=amneziawg; [ "$NODE_PLAIN_WG" = yes ] && _pr=wireguard
    printf '    %s %-9s endpoint %s  subnet %s  mtu %s\n' "$(col "$C_GREEN" "$(printf '%-10s' "$NODE_IFACE")")" "$_pr" "$(bb "$NODE_ENDPOINT:$NODE_LISTEN_PORT")" "$(b "$NODE_ADDRESS")" "$(b "$NODE_MTU")"
  fi
  detect_turn 2>/dev/null || true
  if [ "${#TP_LISTEN[@]}" -gt 0 ]; then echo; echo "  $(b 'Turn-proxy') instances (host services → the node container):"
    for n in "${!TP_LISTEN[@]}"; do wk="${TP_WRAP[$n]}"
      printf '    %s %s → %s   %s\n' "$(col "$C_GREEN" "$(printf '%-22s' "$n")")" "$(bb "${TP_LISTEN[$n]}")" "$(b "${TP_CONNECT[$n]}")" "${wk:+wrap-key $(b "$wk")}"
      printf '        sudo nano /etc/systemd/system/%s.service\n\n' "$n"; done
  fi ;;
esac
echo
echo "  Dir       $(b "$INSTALL_DIR")  ·  edit $(b .env), then $(b "$COMPOSE --profile $PROFILE up -d")"
echo "  Logs      $(b "cd $INSTALL_DIR && $COMPOSE logs -f")"
case "$PROFILE" in host|master) echo "  Next      add entry servers in the panel: $(b 'Nodes → Add node')";; esac
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun$INSTALL_DIR/.env"; }
