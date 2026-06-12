#!/usr/bin/env bash
# uninstall.sh — remove swg-panel. Asks whether to keep wg/awg or remove it too.
#
# Run on any box where install-host.sh or install-node.sh was used. It stops the
# services, removes the panel/agent/node files, units, nginx vhost, users (and any
# legacy queues/ssh keys), and (best effort) the issued TLS cert's renewal. It NEVER
# touches wg/awg
# unless you explicitly choose to.
#
# Fill CONFIG to run unattended, or be prompted. Run as root. --dry-run prints the
# plan and changes nothing.
set -uo pipefail   # not -e: an uninstaller should keep going even if a piece is gone

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
UNINSTALL_WG="${UNINSTALL_WG:-}"             # yes|no — also remove wg/awg (packages + bring interfaces down)
REMOVE_IFACE_CONFS="${REMOVE_IFACE_CONFS:-}" # yes|no — (only with UNINSTALL_WG) delete interface .conf files (erases peer/key data)
KEEP_ROSTER="${KEEP_ROSTER:-}"               # yes|no — keep the peer list + node store (users.json, nodes.json) for a future reinstall
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
HOST=false; NODE=false
if [ -e /opt/swg-panel ] || [ -e /etc/systemd/system/swg-panel-server.service ]; then HOST=true; fi
if [ -e /opt/swg-noded ] || [ -e /opt/swg-agent ] || [ -e /etc/systemd/system/swg-noded.service ]; then NODE=true; fi
$HOST || $NODE || die "swg-panel does not appear to be installed here (nothing to do)"
info "Found:$([ $HOST = true ] && printf ' panel-host')$([ $NODE = true ] && printf ' node')"

# read the nginx server_name now, before we delete the vhost (for acme cleanup)
DOMAIN=""
[ -f /etc/nginx/sites-available/swg-panel.conf ] && \
  DOMAIN="$(sed -n 's/[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' /etc/nginx/sites-available/swg-panel.conf | head -n1 | tr -d ' ')"

# ── the question ──
ask_yn "Also UNINSTALL wg/awg? (no = keep the VPN, remove only swg-panel)" n UNINSTALL_WG
if [ "$UNINSTALL_WG" = yes ]; then
  warn "This brings wg/awg interfaces DOWN and removes the packages — the VPN on this box will STOP."
  if ! $DRYRUN; then read -rp "  Type 'yes' to confirm removing wg/awg: " conf </dev/tty || true
    [ "$conf" = yes ] || { UNINSTALL_WG=no; warn "Not confirmed — keeping wg/awg."; }; fi
fi

echo; info "Plan: remove swg-panel$([ "$UNINSTALL_WG" = yes ] && echo ' + wg/awg')$($DRYRUN && echo '  (dry-run)')"

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
rmrf /etc/swg-panel /etc/swg-agent /etc/sudoers.d/swg-agent
rmrf /srv/swg-queue /var/www/wgstats /var/www/acme /var/log/swg-agent /var/lib/swg-noded

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

echo; ok "Uninstall complete.$([ "$UNINSTALL_WG" != yes ] && echo "  wg/awg was left untouched.")"
$DRYRUN && info "That was a dry run — re-run without --dry-run to apply."
