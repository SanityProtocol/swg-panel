#!/usr/bin/env bash
# update.sh — update an existing swg-panel install in place, from the latest GitHub code.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update
#
# bootstrap.sh fetches the latest repo and runs this from it. It AUTO-DETECTS which
# components are installed and refreshes each — covering every shape:
#   bare-metal host / master / node   ·   docker host / host-node / node
# Config + state are preserved (fleet.json, users.json, nodes.json, auth, certs, .env).
# Run as root. --dry-run shows what it would do and changes nothing.
set -euo pipefail

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'
else BOLD=""; RESET=""; C_CYAN=""; C_GREEN=""; C_YEL=""; C_RED=""; fi
info(){ echo "${C_CYAN}▸${RESET} ${BOLD}$*${RESET}"; }
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
stamp(){ $DRYRUN || printf '%s\n' "$NEW_VER" > "$1/VERSION" 2>/dev/null || true; }
oldver(){ cat "$1/VERSION" 2>/dev/null || echo '?'; }

NEW_VER="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will change."
info "swg-panel update → version ${NEW_VER}"
found=0

# ───────────────────────── bare-metal panel (host or master) ─────────────────────────
if [ -f "$PANEL_DIR/swg-panel-server" ]; then
  found=1; info "bare-metal panel: $(oldver "$PANEL_DIR") → $NEW_VER  ($PANEL_DIR)"
  for f in swg-panel-server index.html app.css app.js reconcile.js; do
    [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$PANEL_DIR/"
  done
  [ -f "$SRC/vendor/qrcode.js" ] && { run mkdir -p "$PANEL_DIR/vendor"; run cp "$SRC/vendor/qrcode.js" "$PANEL_DIR/vendor/"; }
  run chmod 755 "$PANEL_DIR/swg-panel-server"
  stamp "$PANEL_DIR"
  run systemctl restart swg-panel-server && ok "restarted swg-panel-server" || warn "couldn't restart swg-panel-server"
fi

# ───────────────────────── bare-metal node daemon (node or master) ─────────────────────────
if [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; then
  found=1; info "bare-metal node: $(oldver "$NODED_DIR") → $NEW_VER  ($AGENT_DIR + $NODED_DIR)"
  [ -d "$AGENT_DIR" ] && [ -f "$SRC/swg-agent" ] && { run cp "$SRC/swg-agent" "$AGENT_DIR/"; run chmod 755 "$AGENT_DIR/swg-agent"; }
  [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-noded" ] && { run cp "$SRC/swg-noded" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-noded"; }
  stamp "$NODED_DIR"
  run systemctl restart swg-noded && ok "restarted swg-noded" || warn "couldn't restart swg-noded"
fi

# ───────────────────────── Docker (host / node / host-node) ─────────────────────────
if [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
  found=1
  # which profile is running? prefer the marker install-docker.sh wrote into .env, else sniff containers
  prof="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1)"
  if [ -z "$prof" ] && have docker; then
    names="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    case "$names" in *swg-panel*) case "$names" in *swg-node*) prof=host-node;; *) prof=host;; esac;; *swg-node*) prof=node;; esac
  fi
  prof="${prof:-host}"
  info "docker ($prof): $(oldver "$DOCKER_DIR") → $NEW_VER  ($DOCKER_DIR) — restaging + rebuild"
  for f in docker-compose.yml Dockerfile Dockerfile.node .dockerignore VERSION \
           swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
    [ -e "$SRC/$f" ] && run cp -a "$SRC/$f" "$DOCKER_DIR/"
  done
  [ -d "$SRC/vendor" ] && run cp -a "$SRC/vendor" "$DOCKER_DIR/"
  [ -d "$SRC/docker" ] && run cp -a "$SRC/docker" "$DOCKER_DIR/"
  if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
  if $DRYRUN; then echo "    [skip] (cd $DOCKER_DIR && $COMPOSE --profile $prof up -d --build)"
  else ( cd "$DOCKER_DIR" && $COMPOSE --profile "$prof" up -d --build ) && ok "docker ($prof) rebuilt + restarted" || warn "compose rebuild failed — check $DOCKER_DIR"; fi
fi

[ "$found" = 1 ] || die "no swg-panel install found (looked in $PANEL_DIR, $NODED_DIR, $DOCKER_DIR)"
echo; ok "Update complete — now on version $NEW_VER."
$DRYRUN && ok "DRY RUN done — nothing changed."
