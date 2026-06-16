#!/usr/bin/env bash
# uninstall.sh — interactive, component-by-component remover for swg-panel.
#
# Detects every installed entity on this box — the bare-metal panel, a bare-metal node,
# a Docker deployment, AmneziaWG, WireGuard, and EACH installed turn-proxy server — lists
# them, then loops through and asks "uninstall or keep?" for each one. Nothing is removed
# without a yes. Run as root. --dry-run prints the plan and changes nothing; --yes assumes
# yes to every component (still asks the destructive sub-questions unless those are preset).
set -uo pipefail   # not -e: an uninstaller should keep going even if a piece is gone

DRYRUN=false; ASSUME_YES=false
for a in "$@"; do case "$a" in --dry-run) DRYRUN=true;; -y|--yes) ASSUME_YES=true;; esac; done

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '0;36')▸$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '0;33')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
b(){ printf '\033[1m%s\033[0m' "$*"; }
run(){ if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }
rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then run rm -rf "$p"; fi; done; }
# ask_yn <prompt> <default> <outvar>  — preset outvar (env) or --yes skips the prompt
ask_yn(){ local v p="$1" d="${2:-n}"; if [ -n "${!3:-}" ]; then return; fi
  if [ ! -t 0 ] && [ ! -e /dev/tty ]; then printf -v "$3" '%s' "$d"; return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }
# ask_comp <label> — the per-component yes/no (honours --yes); returns 0 = uninstall
ask_comp(){ local v; $ASSUME_YES && return 0
  if [ ! -t 0 ] && [ ! -e /dev/tty ]; then return 1; fi   # no tty, not --yes => keep
  read -rp "  Uninstall $(b "$1")? (y/N): " v </dev/tty || true
  case "$v" in [Yy]*) return 0;; *) return 1;; esac; }

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will be changed."

DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
SD="${SYSTEMD_DIR:-/etc/systemd/system}"   # overridable for testing
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ───────────────────────── removal actions ─────────────────────────
REMOVED_PANEL=false; REMOVED_NODE=false

rm_panel(){
  info "Removing swg-panel (control panel)"
  if [ -e $SD/swg-panel-server.service ]; then run systemctl disable --now swg-panel-server; fi
  rmrf $SD/swg-panel-server.service; run systemctl daemon-reload
  rmrf /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf \
       /etc/nginx/conf.d/swg-panel.conf /etc/nginx/.htpasswd-swg
  command -v nginx >/dev/null 2>&1 && { run nginx -t && run systemctl reload nginx || warn "reload nginx manually if it's running"; }
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do
      [ -n "$a" ] && [ -x "$a" ] && { info "Removing acme.sh renewal for $DOMAIN"; run "$a" --remove -d "$DOMAIN" --ecc; break; }
    done
  fi
  rmrf /opt/swg-panel /etc/swg-panel /var/www/wgstats /var/www/acme
  local KEEP_ROSTER="${KEEP_ROSTER:-}"
  ask_yn "  Keep the peer list + node store (users.json, nodes.json) for a future reinstall?" n KEEP_ROSTER
  if [ "$KEEP_ROSTER" = yes ] && [ -f /var/lib/swg-panel/users.json ]; then
    rmrf /var/lib/swg-panel/.ssh /var/lib/swg-panel/configs
    ok "Kept /var/lib/swg-panel/{users,nodes}.json"
  else rmrf /var/lib/swg-panel; fi
  if id swgpanel >/dev/null 2>&1; then run userdel swgpanel; fi
  REMOVED_PANEL=true; ok "swg-panel removed"
}

rm_node(){
  info "Removing swg-node (bare-metal entry server)"
  if [ -e $SD/swg-noded.service ]; then run systemctl disable --now swg-noded; fi
  rmrf $SD/swg-noded.service; run systemctl daemon-reload
  rmrf /opt/swg-agent /opt/swg-noded /srv/swg-queue /var/log/swg-agent /var/lib/swg-noded /etc/sudoers.d/swg-agent
  rmrf /etc/swg-agent   # turn-proxy.json here is just a panel-facing record; a kept turn-proxy keeps running
  for u in swgpush swgagent; do if id "$u" >/dev/null 2>&1; then run userdel -r "$u"; fi; done
  REMOVED_NODE=true; ok "swg-node removed"
}

rm_docker(){
  info "Removing the Docker deployment ($DOCKER_DIR)"
  if command -v docker >/dev/null 2>&1; then
    local DC=""
    if docker compose version >/dev/null 2>&1; then DC="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"; fi
    [ -n "$DC" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ] && \
      run sh -c "cd '$DOCKER_DIR' && $DC --profile host --profile node --profile host-node down --remove-orphans"
    run sh -c 'docker rm -f swg-panel swg-node >/dev/null 2>&1 || true'
    local RMI="${REMOVE_DOCKER_IMAGES:-}"; ask_yn "  Remove the pulled swg-panel / swg-node images too?" n RMI
    [ "$RMI" = yes ] && run sh -c 'docker rmi ghcr.io/sanityprotocol/swg-panel:latest ghcr.io/sanityprotocol/swg-node:latest swg-panel-docker-swg-panel swg-panel-docker-swg-node >/dev/null 2>&1 || true'
  else warn "docker not found — removing the deployment files only."; fi
  local KEEP="${KEEP_DOCKER_DATA:-}"; ask_yn "  Keep the data dir ($DOCKER_DIR/data: login, nodes, certs) for a future reinstall?" n KEEP
  if [ "$KEEP" = yes ]; then
    rmrf "$DOCKER_DIR/.env" "$DOCKER_DIR/docker-compose.yml" "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR/Dockerfile.node" \
         "$DOCKER_DIR/.dockerignore" "$DOCKER_DIR/VERSION" "$DOCKER_DIR/docker" "$DOCKER_DIR/vendor" \
         "$DOCKER_DIR/swg-panel-server" "$DOCKER_DIR/swg-agent" "$DOCKER_DIR/swg-noded" \
         "$DOCKER_DIR/index.html" "$DOCKER_DIR/app.css" "$DOCKER_DIR/app.js" "$DOCKER_DIR/reconcile.js"
    ok "Kept $DOCKER_DIR/data"
  else rmrf "$DOCKER_DIR"; fi
  ok "Docker deployment removed"
}

down_ifaces(){ local dir="$1" tool="$2" f n
  for f in "$dir"/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"
    command -v "$tool" >/dev/null 2>&1 && run "$tool" down "$n"; done; }

rm_awg(){
  info "Removing AmneziaWG"
  down_ifaces /etc/amnezia/amneziawg awg-quick
  local RC="${REMOVE_IFACE_CONFS:-}"; ask_yn "  Delete AmneziaWG configs (/etc/amnezia)? Erases peer/key data." n RC
  [ "$RC" = yes ] && rmrf /etc/amnezia/amneziawg || info "  Left /etc/amnezia configs in place."
  if command -v apt-get >/dev/null 2>&1; then
    run apt-get purge -y amneziawg amneziawg-tools amneziawg-dkms
    run add-apt-repository -y --remove ppa:amnezia/ppa; run apt-get autoremove -y
  else warn "Non-apt system — remove the amneziawg packages with your package manager."; fi
  ok "AmneziaWG removed"
}

rm_wg(){
  info "Removing WireGuard"
  down_ifaces /etc/wireguard wg-quick
  local RC="${REMOVE_WG_CONFS:-}"; ask_yn "  Delete WireGuard configs (/etc/wireguard)? Erases peer/key data." n RC
  [ "$RC" = yes ] && rmrf /etc/wireguard || info "  Left /etc/wireguard configs in place."
  if command -v apt-get >/dev/null 2>&1; then run apt-get purge -y wireguard wireguard-tools; run apt-get autoremove -y
  else warn "Non-apt system — remove the wireguard packages with your package manager."; fi
  ok "WireGuard removed"
}

rm_turn(){ local unit="$1" name fork
  name="$(basename "$unit" .service)"; fork="${name#vk-turn-proxy-}"
  info "Removing turn-proxy ($fork)"
  [ -e "$unit" ] && run systemctl disable --now "$name"
  rmrf "$unit" "$TURN_DIR/$fork"; run systemctl daemon-reload
  # last one out removes the shared dir + the panel-facing record
  ls $SD/vk-turn-proxy-*.service >/dev/null 2>&1 || rmrf "$TURN_DIR" /etc/swg-agent/turn-proxy.json
  ok "turn-proxy ($fork) removed"
}

# ───────────────────────── detect installed components ─────────────────────────
declare -a CLABEL CDETAIL CFN CARG
add(){ CLABEL+=("$1"); CDETAIL+=("$2"); CFN+=("$3"); CARG+=("${4:-}"); }

[ -d /opt/swg-panel ] || [ -f $SD/swg-panel-server.service ] && \
  add "swg-panel" "control panel (/opt/swg-panel)" rm_panel
[ -d /opt/swg-noded ] || [ -d /opt/swg-agent ] || [ -f $SD/swg-noded.service ] && \
  add "swg-node" "bare-metal entry server (swg-noded)" rm_node

DOCKER_OK=false
{ [ -f "$DOCKER_DIR/docker-compose.yml" ] || [ -f "$DOCKER_DIR/.env" ]; } && DOCKER_OK=true
if ! $DOCKER_OK && command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qE '^swg-(panel|node)$' && DOCKER_OK=true; fi
if $DOCKER_OK; then
  dsvc=""; command -v docker >/dev/null 2>&1 && dsvc="$(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^swg-(panel|node)$' | tr '\n' ' ')"
  add "Docker deployment" "${dsvc:-$DOCKER_DIR}[docker]" rm_docker
fi

awg_present(){ ls /etc/amnezia/amneziawg/*.conf >/dev/null 2>&1 || ls $SD/awg*.service >/dev/null 2>&1 \
  || { command -v dpkg >/dev/null 2>&1 && dpkg -l 2>/dev/null | grep -qE '^ii +amneziawg(-tools| |$)'; }; }
wg_present(){ ls /etc/wireguard/*.conf >/dev/null 2>&1 || ls $SD/wg-quick@*.service >/dev/null 2>&1 \
  || { command -v dpkg >/dev/null 2>&1 && dpkg -l 2>/dev/null | grep -qE '^ii +wireguard '; }; }
awg_present && add "AmneziaWG" "$(ls $SD/awg*.service 2>/dev/null | head -n1 || echo /etc/amnezia/amneziawg)" rm_awg
wg_present  && add "WireGuard" "$(ls $SD/wg-quick@*.service 2>/dev/null | head -n1 || echo /etc/wireguard)" rm_wg

for unit in $(ls $SD/vk-turn-proxy-*.service 2>/dev/null || true); do
  fork="$(basename "$unit" .service)"; fork="${fork#vk-turn-proxy-}"
  owner=""; [ -f "$TURN_DIR/$fork/repo.txt" ] && owner="$(cut -d/ -f1 "$TURN_DIR/$fork/repo.txt" 2>/dev/null)"
  add "${owner:-$fork} turn-proxy" "service file: $(basename "$unit")" rm_turn "$unit"
done

N=${#CLABEL[@]}
[ "$N" -gt 0 ] || die "swg-panel does not appear to be installed here (nothing to do)"

# ───────────────────────── list, then prompt per component ─────────────────────────
echo; info "Found these installed components:"
for i in $(seq 0 $((N-1))); do printf '    %s  %s\n' "$(b "${CLABEL[$i]}")" "$(c '0;90')${CDETAIL[$i]}$(c 0)"; done
echo
$ASSUME_YES && info "--yes: every component will be uninstalled (you'll still be asked the destructive sub-questions)." \
            || echo "  You will be prompted to uninstall or keep each component. Please pay attention."
echo

for i in $(seq 0 $((N-1))); do
  if ask_comp "${CLABEL[$i]}"; then "${CFN[$i]}" "${CARG[$i]}"; else info "Kept ${CLABEL[$i]}."; fi
  echo
done

# group cleanup (shared by panel + agent) — only if we removed a bare-metal piece
if { $REMOVED_PANEL || $REMOVED_NODE; } && getent group swg >/dev/null 2>&1; then
  run groupdel swg 2>/dev/null || info "group 'swg' still in use — left in place."
fi
rmdir /etc/swg-agent 2>/dev/null || true

echo; ok "Uninstall complete."
$DRYRUN && info "That was a dry run — re-run without --dry-run to apply."
