#!/usr/bin/env bash
# update.sh — update an existing swg-panel install in place, from the latest GitHub code.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update
#
# bootstrap.sh fetches the latest repo and runs this from it. It AUTO-DETECTS which
# components are installed — covering every shape (bare-metal host / master / node,
# docker host / host-node / node) — compares each one's installed version against the
# fetched one, and for any with an upgrade available PROMPTS whether to upgrade or skip.
# Config + state are preserved (fleet.json, users.json, nodes.json, auth, certs, .env).
#
# Flags:  --dry-run  show what it would do, change nothing
#         -y|--yes   upgrade everything available without prompting
#         -f|--force re-apply even components already on the latest version
set -euo pipefail

DRYRUN=false; ASSUME_YES=false; FORCE=false
for a in "$@"; do case "$a" in
  --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; -f|--force) FORCE=true;;
esac; done
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then BOLD=$'\033[1m'; RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_BLUE=$'\033[38;5;39m'
else BOLD=""; RESET=""; C_CYAN=""; C_GREEN=""; C_YEL=""; C_RED=""; C_BLUE=""; fi
info(){ echo "${C_CYAN}▸${RESET} ${BOLD}$*${RESET}"; }
ok(){   echo "${C_GREEN}✓${RESET} $*"; }
warn(){ echo "${C_YEL}!${RESET} $*" >&2; }
die(){  echo "${C_RED}✗ $*${RESET}" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
stamp(){ $DRYRUN || printf '%s\n' "$NEW_VER" > "$1/VERSION" 2>/dev/null || true; }
oldver(){ cat "$1/VERSION" 2>/dev/null || echo '?'; }
confirm(){ # confirm <prompt> -> 0 yes / 1 no.  --yes or no terminal => yes (you ran update on purpose)
  $ASSUME_YES && return 0
  local v
  if printf '%s %s: ' "$1" "[Y/n]" 2>/dev/null >/dev/tty && IFS= read -r v 2>/dev/null </dev/tty; then
    case "$v" in [Nn]*) return 1;; *) return 0;; esac
  else return 0; fi
}
# should_update <label> <dir> -> 0 proceed / 1 skip (prints up-to-date or skipped)
should_update(){ local label="$1" dir="$2" old; old="$(oldver "$dir")"
  if [ "$old" = "$NEW_VER" ] && ! $FORCE; then ok "$(col_l "$label"): already up to date ($NEW_VER)"; return 1; fi
  if confirm "Upgrade $(col_l "$label") $(col_v "$old → $NEW_VER")?"; then return 0; fi
  warn "$label: skipped (still $old)"; return 1; }
col_l(){ printf '%s%s%s' "$BOLD" "$*" "$RESET"; }
col_v(){ printf '%s%s%s' "$C_BLUE" "$*" "$RESET"; }

NEW_VER="$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)"
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will change."
info "swg-panel update — latest is version $(col_v "$NEW_VER")"
found=0

# ───────────────────────── bare-metal panel (host or master) ─────────────────────────
if [ -f "$PANEL_DIR/swg-panel-server" ]; then
  found=1
  if should_update "bare-metal panel" "$PANEL_DIR"; then
    info "updating bare-metal panel ($PANEL_DIR)"
    for f in swg-panel-server index.html app.css app.js reconcile.js; do
      [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$PANEL_DIR/"
    done
    [ -f "$SRC/vendor/qrcode.js" ] && { run mkdir -p "$PANEL_DIR/vendor"; run cp "$SRC/vendor/qrcode.js" "$PANEL_DIR/vendor/"; }
    run chmod 755 "$PANEL_DIR/swg-panel-server"; stamp "$PANEL_DIR"
    run systemctl restart swg-panel-server && ok "panel updated + restarted" || warn "couldn't restart swg-panel-server"
  fi
fi

# ───────────────────────── bare-metal node daemon (node or master) ─────────────────────────
if [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; then
  found=1
  if should_update "bare-metal node" "$NODED_DIR"; then
    info "updating bare-metal node ($AGENT_DIR + $NODED_DIR)"
    [ -d "$AGENT_DIR" ] && [ -f "$SRC/swg-agent" ] && { run cp "$SRC/swg-agent" "$AGENT_DIR/"; run chmod 755 "$AGENT_DIR/swg-agent"; }
    [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-noded" ] && { run cp "$SRC/swg-noded" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-noded"; }
    stamp "$NODED_DIR"
    run systemctl restart swg-noded && ok "node daemon updated + restarted" || warn "couldn't restart swg-noded"
  fi
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
  if should_update "docker ($prof)" "$DOCKER_DIR"; then
    info "restaging + rebuild ($DOCKER_DIR)"
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
fi

# ───────────────────────── turn-proxy servers (vk-turn-proxy, ones we installed) ─────────────────────────
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
if [ -d "$TURN_DIR" ]; then
  for d in "$TURN_DIR"/*/; do
    [ -f "${d}server" ] && [ -f "${d}version.txt" ] || continue
    found=1
    key="$(basename "$d")"; owner="$(cat "${d}repo.txt" 2>/dev/null || echo '?')"; cur="$(cat "${d}version.txt" 2>/dev/null || echo '?')"
    if $DRYRUN; then latest="v0.0.0-latest"
    else latest="$(curl -fsSL "https://api.github.com/repos/$owner/releases/latest" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || true)"; fi
    [ -n "$latest" ] || { warn "turn-proxy $key ($owner): couldn't reach GitHub for the latest release — skipping"; continue; }
    if [ "$cur" = "$latest" ] && ! $FORCE; then ok "$(col_l "turn-proxy $key") ($owner): already up to date ($cur)"; continue; fi
    if confirm "Upgrade $(col_l "turn-proxy $key") ($owner) $(col_v "$cur → $latest")?"; then
      case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) arch=amd64;; esac
      url="https://github.com/$owner/releases/latest/download/server-linux-$arch"
      info "updating turn-proxy $key ($owner)"
      if run curl -fsSL "$url" -o "${d}server.new" && run chmod +x "${d}server.new" && run mv "${d}server.new" "${d}server"; then
        $DRYRUN || printf '%s\n' "$latest" > "${d}version.txt"
        run systemctl restart "vk-turn-proxy-$key" && ok "turn-proxy $key updated + restarted" || warn "couldn't restart vk-turn-proxy-$key"
      else warn "turn-proxy $key: download failed ($url)"; fi
    else warn "turn-proxy $key: skipped (still $cur)"; fi
  done
fi

[ "$found" = 1 ] || die "no swg-panel install found (looked in $PANEL_DIR, $NODED_DIR, $DOCKER_DIR, $TURN_DIR)"
echo; ok "Update complete."
$DRYRUN && ok "DRY RUN done — nothing changed."
