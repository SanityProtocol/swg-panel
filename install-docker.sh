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
PANEL_DOMAIN="${PANEL_DOMAIN:-}"
PANEL_BASE="${PANEL_BASE:-}"            # optional subpath mount, e.g. /swg
TLS="${TLS:-}"                         # letsencrypt|cloudflare|cf15|selfsigned|none (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare DNS-01: API token with Zone:DNS:Edit + Zone:Read
CF_ORIGIN_TOKEN="${CF_ORIGIN_TOKEN:-${CF_ORIGIN_KEY:-}}"  # cf15: API token with Zone:SSL and Certificates:Edit
PANEL_PORT="${PANEL_PORT:-8443}"
# Node
PANEL_URL="${PANEL_URL:-}"
NODE_TOKEN="${NODE_TOKEN:-}"
NODE_ENDPOINT="${NODE_ENDPOINT:-${ENDPOINT_IP:-}}"
NODE_IFACE="${NODE_IFACE:-awg0}"
NODE_IFACES="${NODE_IFACES:-}"         # several interfaces: "name:port:addr[:proto],…"
NODE_LISTEN_PORT="${NODE_LISTEN_PORT:-51820}"
NODE_ADDRESS="${NODE_ADDRESS:-10.8.0.1/24}"
TLS_VERIFY="${TLS_VERIFY:-}"           # yes/no; blank = ask (node profile) / default no
DNS="${DNS:-1.1.1.1}"

DRYRUN=false
ARGS=("$@"); for a in "${ARGS[@]+"${ARGS[@]}"}"; do [ "$a" = "--dry-run" ] && DRYRUN=true; done
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '0;36')▸$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '0;33')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
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

# ── extra helpers for the turn-proxy step (shared idiom with the bare-metal installers) ──
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_BLUE=$'\033[38;5;39m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
else BOLD=""; RESET=""; C_BLUE=""; C_GREEN=""; C_RED=""; fi
b(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col(){ local _c="$1"; shift; printf '%s%s%s' "$_c" "$*" "$RESET"; }
menu(){ printf '  %s\n      %s\n\n' "$1" "$2"; }
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
ask(){ local v p="$1" d="${2:-}"; read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v 2>/dev/null </dev/tty || v=""; printf -v "$3" '%s' "${v:-$d}"; }
v_ip(){ printf '%s' "$1" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || return 1; local o; for o in ${1//./ }; do [ "$o" -le 255 ] 2>/dev/null || return 1; done; }
v_host(){ v_ip "$1" && return 0; case "$1" in ""|*" "*|*[!a-zA-Z0-9.-]*) return 1;; *) return 0;; esac; }
v_port(){ case "$1" in ""|*[!0-9]*) return 1;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
v_hostport(){ case "$1" in *:*) v_host "${1%%:*}" && v_port "${1##*:}";; *) return 1;; esac; }
v_email(){   case "$1" in ?*@?*.?*) return 0;; *) return 1;; esac; }
v_cftoken(){ [ -n "$1" ]; }
v_cforigin(){ [ -n "$1" ]; }
ask_choice(){ local p="$1" d="$2" var="$3" opts="$4" v o forced rc
  if [ -n "${!var:-}" ]; then for o in $opts; do [ "${!var}" = "$o" ] && return; done; fi
  while :; do
    if read -rp "$p [$(col "$C_BLUE" "$d")]: " v 2>/dev/null </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    for o in $opts; do [ "$v" = "$o" ] && { printf -v "$var" '%s' "$v"; return; }; done
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "‘$v’ is not one of: $opts"
    warn "‘$v’ isn't one of: $opts"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }
ask_valid(){ local p="$1" d="$2" var="$3" fn="$4" hint="$5" v forced rc
  if [ -n "${!var:-}" ]; then "$fn" "${!var}" && return; fi
  while :; do
    if read -rp "$p${d:+ [$(col "$C_BLUE" "$d")]}: " v 2>/dev/null </dev/tty; then rc=0; else rc=1; v=""; fi
    v="${v:-$d}"; forced=no; case "$v" in *' --force') v="${v% --force}"; v="${v%"${v##*[![:space:]]}"}"; forced=yes;; esac
    if "$fn" "$v"; then printf -v "$var" '%s' "$v"; return; fi
    [ "$forced" = yes ] && { warn "forcing: $v"; printf -v "$var" '%s' "$v"; return; }
    [ $rc -ne 0 ] && die "no valid value for ‘$p’"
    warn "$hint"; echo "  re-enter, or append ' --force' to use it anyway"
  done; }

# ── turn-proxy (vk-turn-proxy) — host systemd service forwarding to the published wg port ──
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"; TURN_RECORD="${TURN_RECORD:-/etc/swg-agent/turn-proxy.json}"
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
  curl -fsSL "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true; }
install_turn_binary(){ local key="$1" owner="$2" listen="$3" connect="$4" extra="$5" arch dir bin svc url ver
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
  dir="$TURN_DIR/$key"; bin="$dir/server"; svc="vk-turn-proxy-$key"
  url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
  mkdir -p "$PREFIX$dir"; info "Installing $owner ($listen → $connect)…"
  if $DRYRUN; then echo "    [skip] curl -fsSL $url -o $bin"
  elif ! { curl -fsSL "$url" -o "$PREFIX$bin" && chmod +x "$PREFIX$bin"; }; then warn "download failed ($url) — skipping"; return 0; fi
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
  ok "installed turn-proxy $(col "$C_GREEN" "$key") ($owner ${ver:-?}) — $listen → $connect"; }
install_turn_proxy(){ echo
  menu "$(col "$C_BLUE" wings)"        "For Android — https://github.com/WINGS-N/vk-turn-proxy"
  menu "$(col "$C_BLUE" samosvalishe)" "For Android — https://github.com/samosvalishe/vk-turn-proxy"
  menu "$(col "$C_BLUE" kiper292)"     "For Android — https://github.com/kiper292/vk-turn-proxy"
  menu "$(col "$C_BLUE" anton48)"      "For iOS — https://github.com/anton48/vk-turn-proxy"
  local sel=""; ask_choice "Select turn-proxy repository or enter $(col "$C_RED" skip) to just proceed" "skip" sel "wings samosvalishe kiper292 anton48 skip"
  [ "$sel" = skip ] && return 0
  local owner pub port connect extra; owner="$(turn_repo_owner "$sel")"
  ask_valid "Public IP this turn-proxy is reached at" "${NODE_ENDPOINT:-$(detect_public_ip)}" pub v_host "an IP or hostname"
  ask_valid "Turn-proxy listen port" "56000" port v_port "port must be 1–65535"
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
choose_turn_proxy(){ info "Checking for turn-proxy servers on this host…"; detect_turn; local names ans n
  while :; do
    detect_turn; names=("${!TP_LISTEN[@]}")
    if [ "${#names[@]}" -eq 0 ]; then echo; warn "No turn-proxy servers found on this box."
      printf '  Press %s to skip and proceed or enter "%s" to install a turn-proxy server: ' "$(b Enter)" "$(col "$C_BLUE" new)"
    else echo; printf "  Installed turn-proxy servers:"
      for n in "${names[@]}"; do printf ' %s %s' "$(col "$C_GREEN" "$n")" "$(b "(${TP_LISTEN[$n]} → ${TP_CONNECT[$n]})")"; done; echo; echo
      printf '  Press %s to proceed or enter "%s" to install another turn-proxy server: ' "$(b Enter)" "$(col "$C_BLUE" new)"; fi
    if ! read -r ans 2>/dev/null </dev/tty; then echo; warn "no interactive input — skipping turn-proxy step"; break; fi
    ans="${ans//[[:space:]]/}"; [ "$ans" = new ] && { install_turn_proxy; continue; }
    [ -z "$ans" ] && break; warn 'type nothing to proceed, or "new" to install a turn-proxy server'
  done; write_turn_record; }

# ───────────────────────── flags ─────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)              PROFILE="${2:-host}"; shift 2 || shift;;
    host|node|host-node)    PROFILE="$1"; shift;;          # bare positional profile (e.g. "docker node")
    -pass|--pass|-password) PANEL_PASSWORD="${2:-}"; shift 2 || shift;;
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
info "DOCKER SETUP (profile: $PROFILE)"
ask_panel_login(){   # match bare-metal: prompt domain + username, auto-generate the password (printed at the end)
  [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN="$(ask_tty "Panel domain or IP" "$(detect_public_ip)")"
  [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
  [ "${PANEL_USER:-admin}" = admin ] && PANEL_USER="admin$(( RANDOM % 900 + 100 ))"   # suggest admin+3 digits, like bare-metal
  PANEL_USER="$(ask_tty "Panel admin username" "$PANEL_USER")"; [ -z "$PANEL_USER" ] && PANEL_USER=admin
  [ -z "$PANEL_PASSWORD" ] && PANEL_PASSWORD="$(rand_pw)"   # auto-generated; pass -pass to set your own
  return 0   # never let a short-circuited && above make the function (and set -e) fail
}
ask_panel_tls(){     # match bare-metal Step 3 — issued INSIDE the container by the bundled acme.sh
  if [ -z "$TLS" ]; then
    echo; echo "$(b 'TLS certificate')"
    menu "$(b "$(col "$C_BLUE" 'letsencrypt (default)')")" "Let's Encrypt cert via acme.sh HTTP-01 (publish port 80: -p 80:80)"
    menu "$(col "$C_BLUE" cloudflare)"                    "Let's Encrypt cert, validated via Cloudflare DNS-01 (no port 80) — needs a Zone:DNS:Edit+Read token + email"
    menu "$(col "$C_BLUE" cf15)"                          "Cloudflare Origin certificate, 15 years — ONLY valid behind Cloudflare's proxy (orange cloud); needs an API token (Zone → SSL and Certificates → Edit)"
    menu "$(col "$C_BLUE" selfsigned)"                    "OK for testing"
    menu "$(col "$C_GREEN" none)"                         "plain HTTP — only behind a tunnel/reverse-proxy that terminates TLS"
  fi
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
                 ask_valid "Cloudflare API token (Zone → SSL and Certificates → Edit)" "$CF_ORIGIN_TOKEN" CF_ORIGIN_TOKEN v_cforigin "paste an API token — the legacy Origin CA Key is deprecated (sunset 2026-09-30)";;
  esac
  return 0
}
ask_node_conn(){     # prompt panel URL + key + endpoint + TLS-verify (for node)
  [ -z "$PANEL_URL" ]   && PANEL_URL="$(ask_tty "Panel URL (https://host[/subpath])" "")"
  [ -n "$PANEL_URL" ]   || die "panel URL required — pass -host (or enter it)"
  [ -z "$NODE_TOKEN" ]  && NODE_TOKEN="$(ask_tty "Node enrollment key (from Nodes → Add node)" "")"
  [ -n "$NODE_TOKEN" ]  || die "node key required — pass -key (create the node in the Nodes screen first)"
  [ -z "$NODE_ENDPOINT" ] && NODE_ENDPOINT="$(ask_tty "Endpoint IP clients dial for this node" "$(detect_public_ip)")"
  [ -n "$NODE_ENDPOINT" ] || die "node endpoint required — pass -endpoint"
  [ -z "$TLS_VERIFY" ]  && TLS_VERIFY="$(ask_yn_tty "Verify the panel's TLS certificate? (no if the panel uses a self-signed cert)" n)"
  return 0
}
case "$PROFILE" in
  host)
    ask_panel_login; ask_panel_tls
    NODE_TOKEN="${NODE_TOKEN:-set-in-nodes-screen}"; PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"; NODE_ENDPOINT="${NODE_ENDPOINT:-127.0.0.1}"
    ;;
  host-node)
    ask_panel_login; ask_panel_tls
    [ -z "$PANEL_URL" ] && PANEL_URL="https://swg-panel:8443"   # local node reaches the panel on the compose net
    [ -z "$NODE_TOKEN" ]  && NODE_TOKEN="$(ask_tty "Node enrollment key (from Nodes → Add node)" "")"
    [ -n "$NODE_TOKEN" ]  || die "node key required — bring up 'docker host' first, add the node, then re-run as host-node with -key"
    [ -z "$NODE_ENDPOINT" ] && NODE_ENDPOINT="$(ask_tty "Endpoint IP clients dial for this node" "$(detect_public_ip)")"
    [ -n "$NODE_ENDPOINT" ] || die "node endpoint required — pass -endpoint"
    TLS_VERIFY="${TLS_VERIFY:-no}"   # local node → local panel is self-signed on the compose net
    ;;
  node)
    ask_node_conn
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
TLS_VERIFY=$TLS_VERIFY
DNS=$DNS
EOF
chmod 600 "$PREFIX$INSTALL_DIR/.env" 2>/dev/null || true
ok "wrote $INSTALL_DIR/.env (profile $PROFILE)"

# ───────────────────────── bring it up ─────────────────────────
info "Starting compose profile '$PROFILE'"
if $DRYRUN; then echo "    [skip] (cd $INSTALL_DIR && $COMPOSE --profile $PROFILE up -d --build)"
else ( cd "$INSTALL_DIR" && $COMPOSE --profile "$PROFILE" up -d --build ); fi

# ───────────────────────── turn-proxy (node-bearing profiles) ─────────────────────────
# Runs on the HOST (systemd) and forwards to the wg UDP port the swg-node container publishes.
if [ "$PROFILE" = node ] || [ "$PROFILE" = host-node ]; then
  echo; info "TURN-PROXY setup (https://github.com/cacggghp/vk-turn-proxy)"; echo
  choose_turn_proxy
fi

# ───────────────────────── handoff ─────────────────────────
echo; ok "Docker install complete (profile: $PROFILE)."
case "$PROFILE" in
  host|host-node)
    SCH=https; [ "$TLS" = none ] && SCH=http
    echo "  UI:    ${SCH}://${PANEL_DOMAIN}:${PANEL_PORT}${PANEL_BASE}/   (login: ${PANEL_USER} / ${PANEL_PASSWORD})"
    echo "  Then:  Nodes → Add node for each entry server (gives a one-time key + command)."
    [ "$PROFILE" = host-node ] && echo "  This box also runs a local node (swg-node) against the panel."
    ;;
  node)
    echo "  Node syncing to ${PANEL_URL} (endpoint ${NODE_ENDPOINT}); it turns green in the Nodes screen shortly."
    ;;
esac
echo "  Dir:   $INSTALL_DIR   (edit .env there, then: $COMPOSE --profile $PROFILE up -d)"
echo "  Logs:  cd $INSTALL_DIR && $COMPOSE logs -f"
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun$INSTALL_DIR/.env"; }
