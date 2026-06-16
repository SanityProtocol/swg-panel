#!/usr/bin/env bash
# uninstall.sh — remove swg-panel (bare-metal host/node AND Docker), turn-proxies optional.
#
# Run on any box where install-host.sh / install-node.sh / install-docker.sh was used. It
# detects what's present and removes it: bare-metal stops the services and removes the
# panel/agent/node files, units, nginx vhost, users (and the issued TLS cert's renewal);
# Docker brings the compose stack down and removes the deployment dir. It NEVER touches
# wg/awg or the turn-proxy servers unless you explicitly choose to.
#
# Fill CONFIG to run unattended, or be prompted. Run as root. --dry-run prints the plan
# and changes nothing.
set -uo pipefail   # not -e: an uninstaller should keep going even if a piece is gone

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
UNINSTALL_WG="${UNINSTALL_WG:-}"             # yes|no — also remove wg/awg (packages + bring interfaces down)
REMOVE_IFACE_CONFS="${REMOVE_IFACE_CONFS:-}" # yes|no — (only with UNINSTALL_WG) delete interface .conf files (erases peer/key data)
KEEP_ROSTER="${KEEP_ROSTER:-}"               # yes|no — keep the peer list + node store (users.json, nodes.json) for a future reinstall
KEEP_DOCKER_DATA="${KEEP_DOCKER_DATA:-}"     # yes|no — keep the Docker data dir (login, nodes, certs) for a future reinstall
REMOVE_DOCKER_IMAGES="${REMOVE_DOCKER_IMAGES:-}"  # yes|no — also remove the pulled swg-panel/swg-node images
UNINSTALL_TURN="${UNINSTALL_TURN:-}"         # yes|no — also remove the installed vk-turn-proxy server(s)
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '0;36')▸$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '0;33')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
run(){ if $DRYRUN; then echo "    [dry] $*"; else "$@"; fi; }
rmrf(){ local p; for p in "$@"; do if [ -e "$p" ] || [ -L "$p" ]; then run rm -rf "$p"; fi; done; }
ask_yn(){ local v p="$1" d="${2:-n}"; if [ -n "${!3:-}" ]; then return; fi
  if [ ! -t 0 ] && [ ! -e /dev/tty ]; then printf -v "$3" '%s' "$d"; return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && info "DRY RUN — nothing will be changed."

# ── detect what's here ──
HOST=false; NODE=false; DOCKER=false; TURN=false
[ -e /opt/swg-panel ] || [ -e /etc/systemd/system/swg-panel-server.service ] && HOST=true
[ -e /opt/swg-noded ] || [ -e /opt/swg-agent ] || [ -e /etc/systemd/system/swg-noded.service ] && NODE=true

DOCKER_DIR="${SWG_DOCKER_DIR:-/opt/swg-panel-docker}"
{ [ -f "$DOCKER_DIR/docker-compose.yml" ] || [ -f "$DOCKER_DIR/.env" ]; } && DOCKER=true
if ! $DOCKER && command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qE '^swg-(panel|node)$' && DOCKER=true
fi

TURN_DIR="${TURN_DIR:-/opt/vk-turn-proxy}"
TURN_UNITS="$(ls /etc/systemd/system/vk-turn-proxy-*.service 2>/dev/null || true)"
{ [ -n "$TURN_UNITS" ] || [ -d "$TURN_DIR" ] || [ -f /etc/swg-agent/turn-proxy.json ]; } && TURN=true
TURN_NAMES=""; for u in $TURN_UNITS; do TURN_NAMES="$TURN_NAMES $(basename "$u" .service)"; done; TURN_NAMES="${TURN_NAMES# }"

$HOST || $NODE || $DOCKER || $TURN || die "swg-panel does not appear to be installed here (nothing to do)"
info "Found:$($HOST && printf ' panel-host')$($NODE && printf ' node')$($DOCKER && printf ' docker')$($TURN && printf ' turn-proxy')"

# read the nginx server_name now, before we delete the vhost (for acme cleanup)
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ── question: wg/awg (bare-metal only) ──
if $HOST || $NODE; then
  ask_yn "Also UNINSTALL wg/awg? (no = keep the VPN, remove only swg-panel)" n UNINSTALL_WG
  if [ "$UNINSTALL_WG" = yes ]; then
    warn "This brings wg/awg interfaces DOWN and removes the packages — the VPN on this box will STOP."
    if ! $DRYRUN; then read -rp "  Type 'yes' to confirm removing wg/awg: " conf </dev/tty || true
      [ "$conf" = yes ] || { UNINSTALL_WG=no; warn "Not confirmed — keeping wg/awg."; }; fi
  fi
else UNINSTALL_WG=no; fi

echo; info "Plan: remove$($HOST || $NODE && echo ' swg-panel(bare-metal)')$($DOCKER && echo ' docker-deployment')$([ "$UNINSTALL_WG" = yes ] && echo ' + wg/awg')$($DRYRUN && echo '  (dry-run)')"

# ═══════════════ bare-metal host/node ═══════════════
if $HOST || $NODE; then
  # ── stop & remove services ──
  info "Services + units"
  for svc in swg-panel-server swg-noded; do
    if [ -e "/etc/systemd/system/$svc.service" ]; then run systemctl disable --now "$svc"; fi
    rmrf "/etc/systemd/system/$svc.service"
  done
  run systemctl daemon-reload

  # ── nginx vhost + basic-auth ──
  info "nginx vhost"
  rmrf /etc/nginx/sites-enabled/swg-panel.conf /etc/nginx/sites-available/swg-panel.conf \
       /etc/nginx/conf.d/swg-panel.conf /etc/nginx/.htpasswd-swg
  if command -v nginx >/dev/null 2>&1; then run nginx -t && run systemctl reload nginx || warn "reload nginx manually if it's running"; fi

  # ── TLS: stop auto-renewal for our domain (best effort; leaves other certs alone) ──
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do
      if [ -n "$a" ] && [ -x "$a" ]; then info "Removing acme.sh renewal for $DOMAIN"; run "$a" --remove -d "$DOMAIN" --ecc; break; fi
    done
  fi

  # ── panel / agent / collector files ──
  info "Files + queues"
  rmrf /opt/swg-panel /opt/swg-agent /opt/swg-noded
  rmrf /etc/swg-panel /etc/sudoers.d/swg-agent
  rmrf /srv/swg-queue /var/www/wgstats /var/www/acme /var/log/swg-agent /var/lib/swg-noded
  # /etc/swg-agent may hold the turn-proxy record — keep it if turn-proxy is being kept
  if $TURN && [ "${UNINSTALL_TURN:-}" != yes ]; then
    rmrf /etc/swg-agent/agent.json /etc/swg-agent/auth.* /etc/swg-agent/*.key 2>/dev/null
    info "Kept /etc/swg-agent/turn-proxy.json (turn-proxy left in place)"
  else
    rmrf /etc/swg-agent
  fi

  # roster (peer list)
  [ -z "$KEEP_ROSTER" ] && ask_yn "Keep the peer list + node store (users.json, nodes.json) for a future reinstall?" n KEEP_ROSTER
  if [ "$KEEP_ROSTER" = yes ] && [ -f /var/lib/swg-panel/users.json ]; then
    rmrf /var/lib/swg-panel/.ssh /var/lib/swg-panel/configs
    ok "Kept /var/lib/swg-panel/{users,nodes}.json (remove them yourself when no longer needed)"
  else
    rmrf /var/lib/swg-panel
  fi

  # ── users + group ──
  info "Users"
  if id swgpanel >/dev/null 2>&1; then run userdel swgpanel; fi          # home is a data dir, handled above
  for u in swgpush swgagent; do if id "$u" >/dev/null 2>&1; then run userdel -r "$u"; fi; done
  if getent group swg >/dev/null 2>&1; then run groupdel swg; fi

  # ── wg/awg (only if chosen) ──
  if [ "$UNINSTALL_WG" = yes ]; then
    info "Bringing wg/awg interfaces down"
    for f in /etc/amnezia/amneziawg/*.conf; do [ -e "$f" ] || continue
      n="$(basename "$f" .conf)"; command -v awg-quick >/dev/null 2>&1 && run awg-quick down "$n"; done
    for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue
      n="$(basename "$f" .conf)"; command -v wg-quick >/dev/null 2>&1 && run wg-quick down "$n"; done

    [ -z "$REMOVE_IFACE_CONFS" ] && ask_yn "Delete interface config files (/etc/amnezia, /etc/wireguard)? Erases peer/key data." n REMOVE_IFACE_CONFS
    if [ "$REMOVE_IFACE_CONFS" = yes ]; then rmrf /etc/amnezia/amneziawg /etc/wireguard; else info "Left interface .conf files in place."; fi

    if command -v apt-get >/dev/null 2>&1; then
      info "Removing packages"
      run apt-get purge -y amneziawg amneziawg-tools amneziawg-dkms
      run apt-get purge -y wireguard wireguard-tools
      run add-apt-repository -y --remove ppa:amnezia/ppa
      run apt-get autoremove -y
    else
      warn "Non-apt system — remove the wg/awg packages with your package manager."
    fi
  fi
fi

# ═══════════════ Docker deployment ═══════════════
if $DOCKER; then
  info "Docker deployment ($DOCKER_DIR)"
  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then DC="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"; else DC=""; fi
    if [ -n "$DC" ] && [ -f "$DOCKER_DIR/docker-compose.yml" ]; then
      info "Stopping + removing containers"
      run sh -c "cd '$DOCKER_DIR' && $DC --profile host --profile node --profile host-node down --remove-orphans"
    fi
    run sh -c 'docker rm -f swg-panel swg-node >/dev/null 2>&1 || true'   # fallback / belt-and-suspenders
    [ -z "$REMOVE_DOCKER_IMAGES" ] && ask_yn "Remove the pulled swg-panel / swg-node images too?" n REMOVE_DOCKER_IMAGES
    if [ "$REMOVE_DOCKER_IMAGES" = yes ]; then
      run sh -c 'docker rmi ghcr.io/sanityprotocol/swg-panel:latest ghcr.io/sanityprotocol/swg-node:latest >/dev/null 2>&1 || true'
      run sh -c 'docker rmi swg-panel-docker-swg-panel swg-panel-docker-swg-node >/dev/null 2>&1 || true'   # legacy local-build tags
    fi
  else
    warn "docker not found — removing the deployment files only."
  fi
  [ -z "$KEEP_DOCKER_DATA" ] && ask_yn "Keep the Docker data dir ($DOCKER_DIR/data: login, nodes, certs) for a future reinstall?" n KEEP_DOCKER_DATA
  if [ "$KEEP_DOCKER_DATA" = yes ]; then
    rmrf "$DOCKER_DIR/.env" "$DOCKER_DIR/docker-compose.yml" "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR/Dockerfile.node" \
         "$DOCKER_DIR/.dockerignore" "$DOCKER_DIR/VERSION" "$DOCKER_DIR/docker" "$DOCKER_DIR/vendor" \
         "$DOCKER_DIR/swg-panel-server" "$DOCKER_DIR/swg-agent" "$DOCKER_DIR/swg-noded" \
         "$DOCKER_DIR/index.html" "$DOCKER_DIR/app.css" "$DOCKER_DIR/app.js" "$DOCKER_DIR/reconcile.js"
    ok "Kept $DOCKER_DIR/data (remove it yourself when no longer needed)"
  else
    rmrf "$DOCKER_DIR"
  fi
fi

# ═══════════════ turn-proxy servers (host systemd; bare-metal OR docker nodes) ═══════════════
if $TURN; then
  info "Turn-proxy server(s):${TURN_NAMES:+ $TURN_NAMES}"
  ask_yn "Also uninstall the turn-proxy server(s)?" n UNINSTALL_TURN
  if [ "$UNINSTALL_TURN" = yes ]; then
    for u in $TURN_UNITS; do
      n="$(basename "$u" .service)"
      [ -e "$u" ] && run systemctl disable --now "$n"
      rmrf "$u"
    done
    run systemctl daemon-reload
    rmrf "$TURN_DIR" /etc/swg-agent/turn-proxy.json
    rmdir /etc/swg-agent 2>/dev/null || true
    ok "Removed turn-proxy server(s)."
  else
    info "Left turn-proxy server(s) in place."
  fi
fi

echo; ok "Uninstall complete.$([ "$UNINSTALL_WG" != yes ] && { $HOST || $NODE; } && echo '  wg/awg was left untouched.')$([ "${UNINSTALL_TURN:-}" != yes ] && $TURN && echo '  turn-proxy left running.')"
$DRYRUN && info "That was a dry run — re-run without --dry-run to apply."
