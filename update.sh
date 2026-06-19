#!/usr/bin/env bash
# update.sh — update an existing swg-panel install in place, from the latest GitHub code.
#
#   curl -fsSL https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh | sudo bash -s update
#
# bootstrap.sh fetches the latest repo and runs this from it. It AUTO-DETECTS which
# components are installed — covering every shape (bare-metal host / master / node,
# docker host / master / node) — compares each one's installed version against the
# fetched one, and for any with an upgrade available PROMPTS whether to upgrade or skip.
# Config + state are preserved (fleet.json, users.json, nodes.json, auth, certs, .env).
#
# Flags:  --dry-run       show what it would do, change nothing
#         -y|--yes        upgrade everything available without prompting
#         -f|--force      re-apply even components already on the latest version
#         --no-components  swg only (panel/noded/agent) — skip third-party turn-proxy servers
set -euo pipefail

DRYRUN=false; ASSUME_YES=false; FORCE=false; NO_COMPONENTS=false
for a in "$@"; do case "$a" in
  --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; -f|--force) FORCE=true;;
  --no-components) NO_COMPONENTS=true;;
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
# per-component outcome, printed as a summary at the end — so a multi-component box (e.g. a docker
# master AND a bare-metal node on the same host) clearly shows EVERY component was considered.
RESULTS=(); note(){ RESULTS+=("$*"); }
pan_seen=no; nod_seen=no; doc_seen=no

install_update_unit(){   # idempotent: wire one-click host self-update for an existing bare-metal panel
  local st="${STATE_DIR:-/var/lib/swg-panel}" usr="${PANEL_USER:-swgpanel}" trig
  trig="${st}/.update-request"
  if $DRYRUN; then echo "    [skip] install /usr/local/bin/swg-update + swg-update.{service,path} + trigger drop-in"; return 0; fi
  cat > /usr/local/bin/swg-update <<'WRAP'
#!/usr/bin/env bash
# swg-update — fixed root entrypoint for one-click in-place update (swg programs only).
set -euo pipefail
URL="${SWG_BOOTSTRAP_URL:-https://raw.githubusercontent.com/SanityProtocol/swg-panel/main/bootstrap.sh}"
curl -fsSL "$URL" | bash -s update -y --no-components
WRAP
  chmod 755 /usr/local/bin/swg-update
  cat > /etc/systemd/system/swg-update.service <<EOF
[Unit]
Description=swg-panel one-click self-update (swg programs only)

[Service]
Type=oneshot
ExecStart=/usr/local/bin/swg-update
EOF
  cat > /etc/systemd/system/swg-update.path <<EOF
[Unit]
Description=watch for a swg-panel update request

[Path]
PathModified=${trig}
Unit=swg-update.service

[Install]
WantedBy=multi-user.target
EOF
  [ -e "$trig" ] || { : > "$trig"; chown "$usr:swg" "$trig" 2>/dev/null || true; chmod 660 "$trig"; }
  # point the (already-installed) panel at the trigger via a drop-in — don't edit the main unit
  install -d /etc/systemd/system/swg-panel-server.service.d
  printf '[Service]\nEnvironment=SWG_UPDATE_TRIGGER=%s\n' "$trig" \
    > /etc/systemd/system/swg-panel-server.service.d/zz-swg-update.conf
  systemctl daemon-reload
  systemctl enable --now swg-update.path >/dev/null 2>&1 || warn "couldn't enable swg-update.path"
}

# ───────────────────────── bare-metal panel (host or master) ─────────────────────────
if [ -f "$PANEL_DIR/swg-panel-server" ]; then
  found=1; pan_seen=yes; pold="$(oldver "$PANEL_DIR")"
  if should_update "bare-metal panel" "$PANEL_DIR"; then
    info "updating bare-metal panel ($PANEL_DIR)"
    for f in swg-panel-server index.html app.css app.js reconcile.js; do
      [ -f "$SRC/$f" ] && run cp "$SRC/$f" "$PANEL_DIR/"
    done
    # whole vendor/ dir — the buildless SPA needs the vendored Preact + htm ESM, not just qrcode
    [ -d "$SRC/vendor" ] && { run mkdir -p "$PANEL_DIR/vendor"; run cp -a "$SRC/vendor/." "$PANEL_DIR/vendor/"; }
    run chmod 755 "$PANEL_DIR/swg-panel-server"; stamp "$PANEL_DIR"
    install_update_unit                              # ensure one-click host self-update is wired
    if run systemctl restart swg-panel-server; then ok "panel updated + restarted"; note "bare-metal panel: ${pold} → ${NEW_VER}"
    else warn "couldn't restart swg-panel-server"; note "bare-metal panel: updated but RESTART FAILED"; fi
  else note "bare-metal panel: unchanged (${pold})"; fi
fi

# ───────────────────────── bare-metal node daemon (node or master) ─────────────────────────
if [ -f "$NODED_DIR/swg-noded" ] || [ -f "$AGENT_DIR/swg-agent" ]; then
  found=1; nod_seen=yes; nold="$(oldver "$NODED_DIR")"
  if should_update "bare-metal node" "$NODED_DIR"; then
    info "updating bare-metal node ($AGENT_DIR + $NODED_DIR)"
    [ -d "$AGENT_DIR" ] && [ -f "$SRC/swg-agent" ] && { run cp "$SRC/swg-agent" "$AGENT_DIR/"; run chmod 755 "$AGENT_DIR/swg-agent"; }
    [ -d "$NODED_DIR" ] && [ -f "$SRC/swg-noded" ] && { run cp "$SRC/swg-noded" "$NODED_DIR/"; run chmod 755 "$NODED_DIR/swg-noded"; }
    stamp "$NODED_DIR"
    if run systemctl restart swg-noded; then ok "node daemon updated + restarted"; note "bare-metal node: ${nold} → ${NEW_VER}"
    else warn "couldn't restart swg-noded — run: systemctl restart swg-noded"; note "bare-metal node: updated but RESTART FAILED"; fi
  else note "bare-metal node: unchanged (${nold})"; fi
fi

# ───────────────────────── Docker (host / node / master) ─────────────────────────
if [ -d "$DOCKER_DIR" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
  found=1; doc_seen=yes
  # which profile is running? prefer the marker install-docker.sh wrote into .env, else sniff containers
  prof="$(sed -n 's/^# .*profile: *//p' "$DOCKER_DIR/.env" 2>/dev/null | head -1)"
  if [ -z "$prof" ] && have docker; then
    names="$(docker ps --format '{{.Names}}' 2>/dev/null || true)"
    case "$names" in *swg-panel*) case "$names" in *swg-node*) prof=master;; *) prof=host;; esac;; *swg-node*) prof=node;; esac
  fi
  prof="${prof:-host}"   # older installs may carry a host-node marker — compose keeps it as a master alias
  if have docker && docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
  if grep -qE '^[[:space:]]*build:' "$DOCKER_DIR/docker-compose.yml" 2>/dev/null; then
    # build-from-source deployment → restage the source and rebuild (don't touch the user's compose/.env)
    if should_update "docker ($prof, source build)" "$DOCKER_DIR"; then
      info "restaging source + rebuilding ($DOCKER_DIR)"
      for f in Dockerfile Dockerfile.node Dockerfile.turn .dockerignore VERSION \
               swg-panel-server swg-agent swg-noded index.html app.css app.js reconcile.js; do
        [ -e "$SRC/$f" ] && run cp -a "$SRC/$f" "$DOCKER_DIR/"
      done
      [ -d "$SRC/vendor" ] && run cp -a "$SRC/vendor" "$DOCKER_DIR/"
      [ -d "$SRC/docker" ] && run cp -a "$SRC/docker" "$DOCKER_DIR/"; stamp "$DOCKER_DIR"
      if $DRYRUN; then echo "    [skip] (cd $DOCKER_DIR && $COMPOSE --profile $prof up -d --build)"; note "docker ($prof): would rebuild"
      else ( cd "$DOCKER_DIR" && $COMPOSE --profile "$prof" up -d --build ) && { ok "docker ($prof) rebuilt + restarted"; note "docker ($prof): rebuilt"; } || { warn "compose rebuild failed — check $DOCKER_DIR"; note "docker ($prof): rebuild FAILED"; }; fi
    else note "docker ($prof): unchanged"; fi
  else
    # prebuilt-image deployment (default) → just pull the newest image + recreate (no restaging)
    if confirm "Pull the latest image for $(col_l "docker ($prof)")?"; then
      info "pulling latest image + recreating ($DOCKER_DIR)"
      if $DRYRUN; then echo "    [skip] (cd $DOCKER_DIR && $COMPOSE --profile $prof pull && $COMPOSE --profile $prof up -d)"; note "docker ($prof): would pull + recreate"
      else ( cd "$DOCKER_DIR" && $COMPOSE --profile "$prof" pull && $COMPOSE --profile "$prof" up -d ) && { ok "docker ($prof) image pulled + recreated"; note "docker ($prof): image pulled + recreated"; } || { warn "compose pull/up failed — check $DOCKER_DIR"; note "docker ($prof): pull/up FAILED"; }; fi
    else warn "docker ($prof): skipped"; note "docker ($prof): skipped"; fi
  fi
fi

# ───────────────────────── turn-proxy servers (vk-turn-proxy, ones we installed) ─────────────────────────
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
if $NO_COMPONENTS && [ -d "$TURN_DIR" ]; then
  info "skipping third-party components (turn-proxy servers) — --no-components"
elif [ -d "$TURN_DIR" ]; then
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
# call out swg components that weren't present, so a partial-looking run is never a mystery
[ "$pan_seen" = yes ] || note "bare-metal panel: not installed ($PANEL_DIR)"
[ "$nod_seen" = yes ] || note "bare-metal node: not installed ($NODED_DIR)"
[ "$doc_seen" = yes ] || note "docker: not installed ($DOCKER_DIR)"
echo; ok "Update complete."
if [ "${#RESULTS[@]}" -gt 0 ]; then echo; info "Summary (every component on this host):"; for r in "${RESULTS[@]}"; do echo "    • $r"; done; fi
$DRYRUN && ok "DRY RUN done — nothing changed."
