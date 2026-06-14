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
TLS="${TLS:-selfsigned}"               # selfsigned | none
PANEL_PORT="${PANEL_PORT:-8443}"
# Node
PANEL_URL="${PANEL_URL:-}"
NODE_TOKEN="${NODE_TOKEN:-}"
NODE_ENDPOINT="${NODE_ENDPOINT:-${ENDPOINT_IP:-}}"
NODE_IFACE="${NODE_IFACE:-awg0}"
NODE_IFACES="${NODE_IFACES:-}"         # several interfaces: "name:port:addr[:proto],…"
NODE_LISTEN_PORT="${NODE_LISTEN_PORT:-51820}"
NODE_ADDRESS="${NODE_ADDRESS:-10.8.0.1/24}"
TLS_VERIFY="${TLS_VERIFY:-no}"
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

# ───────────────────────── flags ─────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)              PROFILE="${2:-host}"; shift 2 || shift;;
    -pass|--pass|-password) PANEL_PASSWORD="${2:-}"; shift 2 || shift;;
    -domain|--domain)       PANEL_DOMAIN="${2:-}"; shift 2 || shift;;
    -base|--base)           PANEL_BASE="${2:-}"; shift 2 || shift;;
    -port|--port)           PANEL_PORT="${2:-}"; shift 2 || shift;;
    -tls|--tls)             TLS="${2:-}"; shift 2 || shift;;
    -key|--key|-token)      NODE_TOKEN="${2:-}"; shift 2 || shift;;
    -host|--host|-url)      PANEL_URL="${2:-}"; shift 2 || shift;;
    -endpoint|--endpoint)   NODE_ENDPOINT="${2:-}"; shift 2 || shift;;
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
case "$PROFILE" in
  host)
    [ -n "$PANEL_PASSWORD" ] || die "panel password required — pass -pass"
    [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN="$(detect_public_ip)"; [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
    NODE_TOKEN="${NODE_TOKEN:-set-in-nodes-screen}"; PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"; NODE_ENDPOINT="${NODE_ENDPOINT:-127.0.0.1}"
    ;;
  host-node)
    [ -n "$PANEL_PASSWORD" ] || die "panel password required — pass -pass"
    [ -n "$NODE_TOKEN" ]     || die "node key required (Nodes → Add node first) — pass -key"
    [ -n "$NODE_ENDPOINT" ]  || die "node endpoint required — pass -endpoint"
    [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN="$(detect_public_ip)"; [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
    PANEL_URL="${PANEL_URL:-https://swg-panel:8443}"
    ;;
  node)
    [ -n "$NODE_TOKEN" ]    || die "node key required — pass -key"
    [ -n "$PANEL_URL" ]     || die "panel URL required — pass -host https://your-panel"
    [ -n "$NODE_ENDPOINT" ] || die "node endpoint required — pass -endpoint"
    PANEL_PASSWORD="${PANEL_PASSWORD:-unused-on-node-only}"; PANEL_DOMAIN="${PANEL_DOMAIN:-localhost}"
    ;;
esac

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
for f in docker-compose.yml Dockerfile Dockerfile.node .dockerignore \
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
