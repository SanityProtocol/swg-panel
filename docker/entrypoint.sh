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
#    selfsigned (default) | none | letsencrypt | letsencrypt-ip | cloudflare | cf15.  acme.sh state persists
#    under /etc/swg-panel/acme (mounted volume), so a restart renews/reuses rather than re-issues.
ACME="/opt/acme.sh/acme.sh"; ACME_CFG="${ACME_CONFIG:-/etc/swg-panel/acme}"
acme(){ "$ACME" --config-home "$ACME_CFG" "$@"; }
# reliable "is there an ISSUED cert?" check — `acme --info` returns 0 even with none, so check disk
acme_has_cert(){ [ -s "$ACME_CFG/${PANEL_DOMAIN}_ecc/${PANEL_DOMAIN}.cer" ] || [ -s "$ACME_CFG/${PANEL_DOMAIN}/${PANEL_DOMAIN}.cer" ]; }
# call after a failed acme run with its output — flag the common, confusing causes
acme_hint(){ case "$1" in
  *"too many certificates"*|*"rateLimited"*|*"rate limit"*)
    log "  ↳ This is a Let's Encrypt RATE LIMIT (max 5 certs per exact domain per 7 days), NOT a config error. Use TLS=cf15 (Cloudflare Origin cert — not rate-limited) now, or wait for the retry-after time above.";;
  *"Invalid response from"*|*"404"*|*"Timeout during connect"*)
    log "  ↳ HTTP-01 couldn't reach this box on :80 (firewall, or it's behind Cloudflare's proxy). Use TLS=cloudflare (DNS-01) or cf15, or grey-cloud the record.";;
esac; }
selfsigned(){ mkdir -p "$(dirname "$SWG_PANEL_TLS_CERT")"
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) san="DNS:$PANEL_DOMAIN";; *) san="IP:$PANEL_DOMAIN";; esac
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$SWG_PANEL_TLS_KEY" -out "$SWG_PANEL_TLS_CERT" \
    -subj "/CN=$PANEL_DOMAIN" -addext "subjectAltName=$san" >/dev/null 2>&1
  log "generated self-signed certificate (CN=$PANEL_DOMAIN, 10y)"; }
# Only ONE acme entry may install to the panel's cert path. If the panel URL changed (e.g. letsencrypt-ip → a
# domain) across restarts, the old entry still installs to the same file, so acme's renew loop reinstalls whichever
# renewed last — a short-lived IP cert then clobbers the domain cert (Cloudflare then 526s). Drop any OTHER entry
# that targets our cert path before installing this one.
acme_prune_stale(){
  local conf d rp
  for conf in "$ACME_CFG"/*/*.conf; do
    [ -f "$conf" ] || continue
    d="$(sed -n "s/^Le_Domain='\{0,1\}\([^']*\).*/\1/p" "$conf" | head -1)"
    [ -n "$d" ] && [ "$d" != "$PANEL_DOMAIN" ] || continue
    rp="$(sed -n "s/^Le_RealFullChainPath='\{0,1\}\([^']*\).*/\1/p" "$conf" | head -1)"
    [ "$rp" = "$SWG_PANEL_TLS_CERT" ] || continue
    log "removing stale acme entry $d (also installs to $SWG_PANEL_TLS_CERT — would clobber $PANEL_DOMAIN's cert)"
    acme --remove -d "$d" --ecc >/dev/null 2>&1 || true
    rm -rf "$(dirname "$conf")"
  done
}
# --reloadcmd is stored by acme.sh and re-run on every future renewal: SIGHUP makes the
# panel (PID 1) reload the new cert into its live TLS context with no downtime.
acme_install(){ acme_prune_stale
  acme --install-cert -d "$PANEL_DOMAIN" --ecc \
  --key-file "$SWG_PANEL_TLS_KEY" --fullchain-file "$SWG_PANEL_TLS_CERT" \
  --reloadcmd 'kill -HUP 1' >/dev/null 2>&1 \
  || log "WARNING: acme --install-cert failed — the panel may fall back to no/old cert"; }

# A present cert is a SELF-SIGNED placeholder when its issuer == subject. A CA mode must NOT reuse one: it means an
# earlier issuance failed and self-signed (e.g. the credential wasn't there yet), and a validating proxy (Cloudflare
# Full-strict) then rejects it (526) FOREVER because the reused placeholder shadows every re-issue. So for a CA mode
# we re-issue when only a self-signed cert is on disk; a REAL CA cert (issuer != subject) is still reused, which is
# what keeps a restart cheap and rate-limit-safe.
cert_is_selfsigned(){ local i s
  i="$(openssl x509 -in "$1" -noout -issuer 2>/dev/null)"; s="$(openssl x509 -in "$1" -noout -subject 2>/dev/null)"
  [ -n "$i" ] && [ "$i" = "$s" ]; }
# Does cert $1 actually name $PANEL_DOMAIN (in its subject CN or a SAN)? A LEFTOVER cert for a DIFFERENT domain —
# e.g. after flipping swgt2→swgt — is a real CA cert but the wrong one, and reusing it makes the proxy reject it.
cert_covers_domain(){ openssl x509 -in "$1" -noout -text 2>/dev/null | grep -qF "$PANEL_DOMAIN"; }
reuse_present_cert(){
  [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -f "$SWG_PANEL_TLS_CERT" ] || return 1
  case "${TLS:-selfsigned}" in
    # A CA mode reuses the on-disk cert ONLY if it's a REAL CA cert that COVERS this domain; a self-signed
    # placeholder OR a leftover cert for another domain must be RE-ISSUED (which overwrites it) so the change
    # can't be broken by whatever cert happened to be left behind.
    cloudflare|letsencrypt|letsencrypt-ip|cf15) ! cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && cert_covers_domain "$SWG_PANEL_TLS_CERT" ;;
    *) return 0 ;;
  esac; }

if [ "${TLS:-selfsigned}" = "none" ]; then
  # Reverse-proxy: serve plain HTTP — and do so even if a cert is still on disk. A flip FROM direct-TLS→reverse-proxy
  # recreates the container with TLS=none but leaves the old cert in the persisted volume; without this the
  # "cert already present wins" branch below would keep serving HTTPS and the flip to plain HTTP wouldn't take.
  log "TLS=none — serving plain HTTP (login travels in the clear; use only behind a tunnel)"
  unset SWG_PANEL_TLS_CERT SWG_PANEL_TLS_KEY
elif reuse_present_cert; then
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
      # capture acme's full output so a failure shows WHY in 'docker logs' (don't hide it in /dev/null)
      if _out="$(acme --issue -d "$PANEL_DOMAIN" --standalone --server letsencrypt --keylength ec-256 2>&1)" || acme_has_cert; then
        acme_install; log "Let's Encrypt cert installed"
      else
        printf '%s\n' "$_out" | sed 's/^/[acme] /'
        log "WARNING: letsencrypt issuance FAILED (see [acme] lines above). HTTP-01 needs port 80 reachable from the internet and breaks behind Cloudflare's proxy — use TLS=cloudflare (DNS-01) or cf15. Falling back to self-signed."
        acme_hint "$_out"; selfsigned
      fi ;;
    letsencrypt-ip)
      [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
      log "issuing a short-lived (~6 day) Let's Encrypt IP certificate for $PANEL_DOMAIN (HTTP-01 standalone on :80)…"
      # IP certs must use the shortlived profile; --days 3 → the 12h renew loop re-issues ~2 days in (≈4-day buffer)
      if _out="$(acme --issue -d "$PANEL_DOMAIN" --standalone --server letsencrypt --keylength ec-256 --certificate-profile shortlived --days 3 2>&1)" || acme_has_cert; then
        acme_install; log "Let's Encrypt IP cert installed (short-lived; auto-renews every 12h)"
      else
        printf '%s\n' "$_out" | sed 's/^/[acme] /'
        log "WARNING: letsencrypt-ip issuance FAILED (see [acme] lines above). Needs port 80 reachable, a PUBLIC IP, and a direct hit (not behind Cloudflare's proxy). Falling back to self-signed."
        acme_hint "$_out"; selfsigned
      fi ;;
    cloudflare)
      [ -n "${CF_TOKEN:-}" ] || { log "WARNING: TLS=cloudflare but CF_TOKEN unset — falling back to self-signed"; selfsigned; }
      if [ -n "${CF_TOKEN:-}" ]; then
        [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
        log "issuing $PANEL_DOMAIN via Let's Encrypt (DNS-01 through Cloudflare)…"
        if _out="$(CF_Token="$CF_TOKEN" acme --issue -d "$PANEL_DOMAIN" --dns dns_cf --server letsencrypt --keylength ec-256 2>&1)" || acme_has_cert; then
          acme_install; log "Cloudflare DNS-01 cert installed"
        else
          printf '%s\n' "$_out" | sed 's/^/[acme] /'
          log "WARNING: cloudflare (DNS-01) issuance FAILED (see [acme] lines above) — check the token has Zone:DNS:Edit + Zone:Read and that $PANEL_DOMAIN is on that account. Falling back to self-signed."
          acme_hint "$_out"; selfsigned
        fi
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
  "store_configs": true,
  "config_dir":    "/var/lib/swg-panel/configs",
  "node_interval": 5
}
JSON
  log "wrote a starter fleet.json (add nodes in the UI → Nodes)"
fi
mkdir -p "$STATS_DIR" /var/lib/swg-panel
[ -f /var/lib/swg-panel/nodes.json ] || { echo '{}' > /var/lib/swg-panel/nodes.json; log "seeded empty nodes.json"; }

# 4) Auto-renewal — only the acme-managed modes have something to renew. acme.sh re-issues
#    a cert once it enters its renewal window and then runs the saved --reloadcmd (kill -HUP 1),
#    so the panel reloads the fresh cert without a restart. cf15/selfsigned (long-lived) and
#    none/mounted certs aren't acme-managed, so no loop is started for them.
case "${TLS:-selfsigned}" in
  letsencrypt|letsencrypt-ip|cloudflare)
    # Don't silence failures — a stalled renewal must be visible in the logs (the panel also watches its own
    # cert expiry and warns in the UI, but a loud log line is the first breadcrumb). On failure, retry sooner
    # (1h) instead of waiting a full 12h, so we get more attempts inside the renewal buffer.
    ( while :; do
        if out=$(acme --cron 2>&1); then sleep 43200
        else log "WARNING: TLS auto-renewal failed — retrying in 1h. last: $(printf '%s' "$out" | tail -1)"; sleep 3600; fi
      done ) &
    log "TLS auto-renewal enabled (acme.sh --cron every 12h; 1h retry on failure; reload via SIGHUP)" ;;
esac

log "starting swg-panel-server on ${SWG_PANEL_HOST:-0.0.0.0}:${SWG_PANEL_PORT:-8443}"
exec "${SWG_PANEL_BIN:-/opt/swg-panel/swg-panel-server}"
