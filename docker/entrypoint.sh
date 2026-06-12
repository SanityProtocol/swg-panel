#!/bin/sh
# swg-panel container entrypoint. Materialises a login + TLS cert + a starter
# fleet.json from env / mounted volumes, then execs the broker. Mirrors the
# standalone bare-metal install, driven by env instead of the installer.
set -eu

log() { printf '\033[0;36m[entrypoint]\033[0m %s\n' "$*"; }

PANEL_USER="${PANEL_USER:-admin}"
PANEL_DOMAIN="${PANEL_DOMAIN:-localhost}"
STATS_DIR="${STATS_DIR:-/var/www/wgstats}"

# 1) Login: a mounted auth file wins; else generate from PANEL_PASSWORD; else no auth.
if [ -n "${SWG_PANEL_AUTH:-}" ] && [ ! -f "$SWG_PANEL_AUTH" ]; then
  if [ -n "${PANEL_PASSWORD:-}" ]; then
    mkdir -p "$(dirname "$SWG_PANEL_AUTH")"
    python3 - "$PANEL_USER" "$PANEL_PASSWORD" > "$SWG_PANEL_AUTH" <<'PY'
import sys, os, hashlib, base64
u, pw = sys.argv[1], sys.argv[2]
salt = os.urandom(16); it = 200000
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
print("%s:pbkdf2_sha256$%d$%s$%s" % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
PY
    chmod 600 "$SWG_PANEL_AUTH"
    log "login configured for user '$PANEL_USER'"
  else
    log "WARNING: no PANEL_PASSWORD and no auth file mounted — running WITHOUT a login"
    unset SWG_PANEL_AUTH
  fi
fi

# 2) TLS: a mounted cert wins; else TLS=selfsigned (default) generates one; TLS=none = plain HTTP.
if [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ ! -f "$SWG_PANEL_TLS_CERT" ]; then
  case "${TLS:-selfsigned}" in
    none)
      log "TLS=none — serving plain HTTP (login travels in the clear; use only behind a tunnel)"
      unset SWG_PANEL_TLS_CERT SWG_PANEL_TLS_KEY ;;
    *)
      mkdir -p "$(dirname "$SWG_PANEL_TLS_CERT")"
      case "$PANEL_DOMAIN" in *[a-zA-Z]*) san="DNS:$PANEL_DOMAIN";; *) san="IP:$PANEL_DOMAIN";; esac
      openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout "$SWG_PANEL_TLS_KEY" -out "$SWG_PANEL_TLS_CERT" \
        -subj "/CN=$PANEL_DOMAIN" -addext "subjectAltName=$san" >/dev/null 2>&1
      log "generated self-signed certificate (CN=$PANEL_DOMAIN, 10y)" ;;
  esac
fi

# 3) fleet.json: use the mounted one; else write a starter. Nodes are managed in
#    the UI (Nodes screen) and live in nodes.json — not listed here.
if [ -n "${SWG_PANEL_FLEET:-}" ] && [ ! -f "$SWG_PANEL_FLEET" ]; then
  mkdir -p "$(dirname "$SWG_PANEL_FLEET")"
  cat > "$SWG_PANEL_FLEET" <<JSON
{
  "roster_path":   "/var/lib/swg-panel/users.json",
  "nodes_path":    "/var/lib/swg-panel/nodes.json",
  "stats_dir":     "$STATS_DIR",
  "store_configs": false,
  "config_dir":    "/var/lib/swg-panel/configs",
  "node_interval": 5
}
JSON
  log "wrote a starter fleet.json (add nodes in the UI → Nodes)"
fi
mkdir -p "$STATS_DIR" /var/lib/swg-panel
[ -f /var/lib/swg-panel/nodes.json ] || { echo '{}' > /var/lib/swg-panel/nodes.json; log "seeded empty nodes.json"; }

log "starting swg-panel-server on ${SWG_PANEL_HOST:-0.0.0.0}:${SWG_PANEL_PORT:-8443}"
exec "${SWG_PANEL_BIN:-/opt/swg-panel/swg-panel-server}"
