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

# 2) TLS — same options as bare-metal, issued inside the container via bundled acme.sh.
#    A mounted cert at $SWG_PANEL_TLS_CERT always wins (skips everything below).
#    selfsigned (default) | none | letsencrypt | cloudflare | cf15.  acme.sh state persists
#    under /etc/swg-panel/acme (mounted volume), so a restart renews/reuses rather than re-issues.
ACME="/opt/acme.sh/acme.sh"; ACME_CFG="${ACME_CONFIG:-/etc/swg-panel/acme}"
acme(){ "$ACME" --config-home "$ACME_CFG" "$@"; }
selfsigned(){ mkdir -p "$(dirname "$SWG_PANEL_TLS_CERT")"
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) san="DNS:$PANEL_DOMAIN";; *) san="IP:$PANEL_DOMAIN";; esac
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$SWG_PANEL_TLS_KEY" -out "$SWG_PANEL_TLS_CERT" \
    -subj "/CN=$PANEL_DOMAIN" -addext "subjectAltName=$san" >/dev/null 2>&1
  log "generated self-signed certificate (CN=$PANEL_DOMAIN, 10y)"; }
acme_install(){ acme --install-cert -d "$PANEL_DOMAIN" --ecc \
  --key-file "$SWG_PANEL_TLS_KEY" --fullchain-file "$SWG_PANEL_TLS_CERT" >/dev/null 2>&1 \
  || log "WARNING: acme --install-cert failed — the panel may fall back to no/old cert"; }

if [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -f "$SWG_PANEL_TLS_CERT" ]; then
  log "using the certificate already present at $SWG_PANEL_TLS_CERT (mounted / previously issued)"
elif [ -n "${SWG_PANEL_TLS_CERT:-}" ]; then
  mkdir -p "$(dirname "$SWG_PANEL_TLS_CERT")" "$ACME_CFG"
  case "${TLS:-selfsigned}" in
    none) log "TLS=none — serving plain HTTP (login travels in the clear; use only behind a tunnel)"
          unset SWG_PANEL_TLS_CERT SWG_PANEL_TLS_KEY ;;
    selfsigned|"") selfsigned ;;
    letsencrypt)
      [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
      log "issuing $PANEL_DOMAIN via Let's Encrypt (HTTP-01 standalone on :80)…"
      if acme --issue -d "$PANEL_DOMAIN" --standalone --server letsencrypt --keylength ec-256 >/dev/null 2>&1 \
         || acme --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then acme_install; log "Let's Encrypt cert installed"
      else log "WARNING: letsencrypt issuance failed (is :80 published + reachable?) — falling back to self-signed"; selfsigned; fi ;;
    cloudflare)
      [ -n "${CF_TOKEN:-}" ] || { log "WARNING: TLS=cloudflare but CF_TOKEN unset — falling back to self-signed"; selfsigned; }
      if [ -n "${CF_TOKEN:-}" ]; then
        [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
        log "issuing $PANEL_DOMAIN via Let's Encrypt (DNS-01 through Cloudflare)…"
        if CF_Token="$CF_TOKEN" acme --issue -d "$PANEL_DOMAIN" --dns dns_cf --server letsencrypt --keylength ec-256 >/dev/null 2>&1 \
           || acme --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then acme_install; log "Cloudflare DNS-01 cert installed"
        else log "WARNING: cloudflare issuance failed — falling back to self-signed"; selfsigned; fi
      fi ;;
    cf15)
      [ -n "${CF_ORIGIN_TOKEN:-}" ] || { log "WARNING: TLS=cf15 but CF_ORIGIN_TOKEN unset — falling back to self-signed"; selfsigned; }
      if [ -n "${CF_ORIGIN_TOKEN:-}" ]; then
        log "requesting a 15-year Cloudflare Origin certificate for $PANEL_DOMAIN…"
        key="$(openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null)"
        csr="$(printf '%s\n' "$key" | openssl req -new -key /dev/stdin -subj "/CN=$PANEL_DOMAIN" 2>/dev/null)"
        cert="$(CF_ORIGIN_TOKEN="$CF_ORIGIN_TOKEN" PANEL_DOMAIN="$PANEL_DOMAIN" CSR="$csr" python3 - <<'PY'
import os,json,urllib.request,urllib.error,sys
body=json.dumps({"hostnames":[os.environ["PANEL_DOMAIN"]],"requested_validity":5475,"request_type":"origin-ecc","csr":os.environ["CSR"]}).encode()
req=urllib.request.Request("https://api.cloudflare.com/client/v4/certificates",data=body,method="POST",
    headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["CF_ORIGIN_TOKEN"]})
try:
    with urllib.request.urlopen(req,timeout=30) as r: d=json.load(r)
except urllib.error.HTTPError as e: d=json.load(e)
except Exception as e: sys.stderr.write(str(e)); sys.exit(1)
sys.stdout.write(d["result"]["certificate"]) if d.get("success") else sys.exit(1)
PY
)" && [ -n "$cert" ] && { printf '%s\n' "$cert" > "$SWG_PANEL_TLS_CERT"; printf '%s\n' "$key" > "$SWG_PANEL_TLS_KEY"; log "Cloudflare Origin cert installed (15y) — valid only behind Cloudflare's proxy"; } \
          || { log "WARNING: cf15 request failed (check CF_ORIGIN_TOKEN / that $PANEL_DOMAIN is on this account) — falling back to self-signed"; selfsigned; }
      fi ;;
    *) log "unknown TLS='$TLS' — using self-signed"; selfsigned ;;
  esac
  [ -n "${SWG_PANEL_TLS_KEY:-}" ] && [ -f "${SWG_PANEL_TLS_KEY:-/nonexistent}" ] && chmod 600 "$SWG_PANEL_TLS_KEY" 2>/dev/null || true
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
