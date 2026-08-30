#!/bin/sh
# swg-panel container entrypoint. Materialises a login + TLS cert + a starter
# fleet.json from env / mounted volumes, then execs the broker. Mirrors the
# standalone bare-metal install, driven by env instead of the installer.
set -eu

log() { printf '\033[0;36m[entrypoint]\033[0m %s\n' "$*"; }

# ─────────────────────── swg-sub certificate (defined up front) ───────────────────────
# Defined here so the `sub-cert <domain>` RUNTIME subcommand — swg-netctl-docker calls `entrypoint.sh sub-cert
# <domain>` when the panel's subscription address changes (a DIFFERENT host the panel cert doesn't cover) — can
# issue swg-sub's cert WITHOUT running the whole panel bootstrap. The boot path below calls the same issue_sub_cert.
ACME="/opt/acme.sh/acme.sh"; ACME_CFG="${ACME_CONFIG:-/etc/swg-panel/acme}"
acme(){ "$ACME" --config-home "$ACME_CFG" "$@"; }
cert_is_selfsigned(){ local i s
  # strip openssl's `issuer=`/`subject=` labels — else the two strings ALWAYS differ and self-signed is never seen.
  i="$(openssl x509 -in "$1" -noout -issuer 2>/dev/null | sed 's/^issuer= *//')"
  s="$(openssl x509 -in "$1" -noout -subject 2>/dev/null | sed 's/^subject= *//')"
  [ -n "$i" ] && [ "$i" = "$s" ]; }
# Does cert $1 cover hostname $2 — an exact SAN/CN, or a single-label *.wildcard (so *.example.com covers
# sub.example.com but not a.b.example.com)?
cert_covers_host(){ local host="$2" dns base pre
  for dns in $(openssl x509 -in "$1" -noout -text 2>/dev/null | grep -oE 'DNS:[^,[:space:]]+' | cut -d: -f2); do
    [ "$dns" = "$host" ] && return 0
    case "$dns" in \*.*) base="${dns#\*.}"; pre="${host%".$base"}"
      [ "$pre" != "$host" ] && [ "$pre" = "${host%%.*}" ] && return 0 ;;
    esac
  done
  return 1; }
# Days until a certificate FILE expires; empty when it cannot be read (no openssl, no file, odd date).
# Empty is never treated as a fault by the caller — "could not tell" must not become "renewal is broken".
cert_days_left(){
  local end epoch now
  [ -s "${1:-}" ] || return 0
  end="$(openssl x509 -in "$1" -noout -enddate 2>/dev/null | cut -d= -f2)"; [ -n "$end" ] || return 0
  epoch="$(date -d "$end" +%s 2>/dev/null)" || return 0
  [ -n "$epoch" ] || return 0
  now="$(date +%s)"; echo $(( (epoch - now) / 86400 ))
}
SUB_TLS_DIR="/etc/swg-sub/tls"; SC="$SUB_TLS_DIR/fullchain.pem"; SK="$SUB_TLS_DIR/key.pem"
sub_selfsigned(){ mkdir -p "$SUB_TLS_DIR"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$SK" -out "$SC" \
    -subj "/CN=$SUB_DOMAIN" -addext "subjectAltName=DNS:$SUB_DOMAIN" >/dev/null 2>&1
  log "swg-sub: generated self-signed cert (CN=$SUB_DOMAIN)"; }
# Ensure swg-sub's cert for $SUB_DOMAIN. Rule: if the panel's OWN cert already covers the sub host (same domain, or a
# SAN/wildcard) reuse it — no second issuance; else issue a SEPARATE cert (own key). Never blocks the caller fatally.
issue_sub_cert(){ set +e
  mkdir -p "$SUB_TLS_DIR"
  if [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -s "$SWG_PANEL_TLS_CERT" ] && [ -s "${SWG_PANEL_TLS_KEY:-/nonexistent}" ] \
       && cert_covers_host "$SWG_PANEL_TLS_CERT" "$SUB_DOMAIN"; then
    cp "$SWG_PANEL_TLS_CERT" "$SC"; cp "$SWG_PANEL_TLS_KEY" "$SK"
    log "swg-sub: panel certificate covers $SUB_DOMAIN — reusing it for the subscription page"
  elif [ -s "$SC" ] && { [ "${TLS:-selfsigned}" = selfsigned ] || ! cert_is_selfsigned "$SC"; } \
       && cert_covers_host "$SC" "$SUB_DOMAIN"; then
    log "swg-sub: reusing present cert for $SUB_DOMAIN"
  else case "${TLS:-selfsigned}" in
    letsencrypt|letsencrypt-ip)
      # The sub never even ATTEMPTED Let's Encrypt: the case below had branches only for cloudflare and cf15, so
      # TLS=letsencrypt fell through to *) and self-signed. The panel got a real cert from its own branch while the
      # subscription page silently did not — and a validating proxy (Cloudflare Full-strict) then answers 526 on
      # every subscription link. HTTP-01 standalone, exactly as the panel does it: same mechanism, no extra
      # credential. Needs :80 reachable FOR THE SUB HOST, which is the same requirement the panel branch carries.
      [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
      if _sout="$(acme --issue -d "$SUB_DOMAIN" --standalone --server letsencrypt --keylength ec-256 2>&1)" \
           || [ -s "$ACME_CFG/${SUB_DOMAIN}_ecc/${SUB_DOMAIN}.cer" ]; then
        if acme --install-cert -d "$SUB_DOMAIN" --ecc --key-file "$SK" --fullchain-file "$SC" --reloadcmd 'true' >/dev/null 2>&1; then
          log "swg-sub: Let's Encrypt cert for $SUB_DOMAIN installed (HTTP-01)"
        else log "WARNING: swg-sub cert issued but could not be installed — falling back to self-signed"; sub_selfsigned; fi
      else
        printf '%s\n' "$_sout" | sed 's/^/[acme-sub] /'
        log "WARNING: swg-sub Let's Encrypt for $SUB_DOMAIN FAILED (see [acme-sub] above) — needs :80 reachable for THAT hostname. Falling back to self-signed."
        sub_selfsigned
      fi ;;
    cloudflare)
      if [ -n "${CF_TOKEN:-}" ] \
         && { CF_Token="$CF_TOKEN" acme --issue -d "$SUB_DOMAIN" --dns dns_cf --server letsencrypt --keylength ec-256 >/dev/null 2>&1 \
              || [ -s "$ACME_CFG/${SUB_DOMAIN}_ecc/${SUB_DOMAIN}.cer" ]; } \
         && acme --install-cert -d "$SUB_DOMAIN" --ecc --key-file "$SK" --fullchain-file "$SC" --reloadcmd 'true' >/dev/null 2>&1; then
        log "swg-sub: Cloudflare DNS-01 cert for $SUB_DOMAIN installed"
      else log "WARNING: swg-sub Cloudflare cert for $SUB_DOMAIN failed — falling back to self-signed (set the sub hostname to CF Flexible, or check the token)"; sub_selfsigned; fi ;;
    cf15)
      _scferr="$(mktemp 2>/dev/null || echo /tmp/cf15sub.err)"
      key="$(openssl ecparam -name prime256v1 -genkey -noout 2>/dev/null)"
      csr="$(printf '%s\n' "$key" | openssl req -new -key /dev/stdin -subj "/CN=$SUB_DOMAIN" 2>/dev/null)"
      cert="$(CF_ORIGIN_TOKEN="${CF_ORIGIN_TOKEN:-}" PANEL_DOMAIN="$SUB_DOMAIN" CSR="$csr" python3 - <<'PY'
import os,json,urllib.request,urllib.error,sys
body=json.dumps({"hostnames":[os.environ["PANEL_DOMAIN"]],"requested_validity":5475,"request_type":"origin-ecc","csr":os.environ["CSR"]}).encode()
req=urllib.request.Request("https://api.cloudflare.com/client/v4/certificates",data=body,method="POST",
    headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["CF_ORIGIN_TOKEN"]})
try:
    with urllib.request.urlopen(req,timeout=30) as r: d=json.load(r)
except urllib.error.HTTPError as e: d=json.load(e)
except Exception as e: sys.stderr.write(str(e)); sys.exit(1)
if d.get("success"):
    sys.stdout.write(d["result"]["certificate"])
else:
    # Say WHAT Cloudflare objected to. Exiting mute left "cf15 request failed" and three things to guess
    # between (wrong token, wrong scope, zone not on this account); the bare-metal path has always printed
    # this, so the container was strictly worse at the same job.
    for _e in (d.get("errors") or [{"message": "unknown error"}]):
        sys.stderr.write("%s (code %s)\n" % (_e.get("message", "?"), _e.get("code", "?")))
    sys.exit(1)
PY
)" 2>"$_scferr" && [ -n "$cert" ] && { mkdir -p "$SUB_TLS_DIR"; printf '%s\n' "$cert" > "$SC"; printf '%s\n' "$key" > "$SK"; log "swg-sub: Cloudflare Origin cert for $SUB_DOMAIN installed (15y)"; } \
        || { log "WARNING: swg-sub cf15 cert for $SUB_DOMAIN failed — Cloudflare's response:"
             while IFS= read -r _l; do [ -n "$_l" ] && log "  [cf] $_l"; done < "$_scferr"
             sub_selfsigned; }
      rm -f "$_scferr" 2>/dev/null || true ;;
    *) sub_selfsigned ;;
  esac; fi
  [ -f "$SK" ] && chmod 600 "$SK" 2>/dev/null || true
  return 0; }
# Runtime subcommand (panel-managed): re-issue swg-sub's cert for a specific domain, then exit — no panel bootstrap.
if [ "${1:-}" = "sub-cert" ]; then
  SUB_DOMAIN="${2:-${SUB_DOMAIN:-}}"
  [ -n "${SUB_DOMAIN:-}" ] || { log "sub-cert: no domain given"; exit 2; }
  issue_sub_cert; exit 0
fi

PANEL_USER="${PANEL_USER:-admin}"
PANEL_DOMAIN="${PANEL_DOMAIN:-localhost}"
STATS_DIR="${STATS_DIR:-/var/www/wgstats}"

# 1) Login: a mounted (non-empty) auth file wins; else generate from PANEL_PASSWORD; else no auth.
# NOTE: -s (not -f) is deliberate — the swg-sub service's `/dev/null:/etc/swg-panel/auth` bind mount makes docker
# create an EMPTY ./data/etc/auth on the host as its mount target, BEFORE this entrypoint runs. With -f that empty
# file would be mistaken for "auth already set" and we'd skip generation → the panel would run with NO login. -s
# regenerates from PANEL_PASSWORD whenever the file is missing OR empty, while a real mounted auth still wins.
if [ -n "${SWG_PANEL_AUTH:-}" ] && [ ! -s "$SWG_PANEL_AUTH" ]; then
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
#    (ACME/acme() are defined at the top of this file, alongside the sub-cert helpers.)
# reliable "is there an ISSUED cert?" check — `acme --info` returns 0 even with none, so check disk.
# ⚠️ It must test the file --install-cert READS (fullchain.cer) and that the leaf is really a PEM:
# acme.sh ≤3.1.3 writes the CA's HTTP body to <domain>.cer unconditionally, so a 404 from the CA
# leaves a JSON error blob that a bare -s test happily reports as a certificate. Here that turns the
# `|| acme_has_cert` rescues below into false successes, and the panel then starts with no usable
# TLS. The image pins acme.sh past that bug, but the acme state dir is a MOUNTED VOLUME — it can
# still carry a blob written by an older image, so the predicate stays defensive.
acme_has_cert(){
  local d
  for d in "$ACME_CFG/${PANEL_DOMAIN}_ecc" "$ACME_CFG/${PANEL_DOMAIN}"; do
    [ -s "$d/fullchain.cer" ] || continue
    head -1 "$d/${PANEL_DOMAIN}.cer" 2>/dev/null | grep -q 'BEGIN CERTIFICATE' && return 0
  done
  return 1; }
# ⚠️ A FAILED ORDER LEAVES A TRAP THAT NO RESTART CAN CLEAR. acme.sh writes <domain>.key before it ever
# contacts the CA and keeps it when the order fails; every later --issue then stops at "Domain key exists,
# do you want to overwrite it? ... add '--force'" instead of reaching the CA. So the real reason (port 80
# unreachable behind a proxy, a bad DNS token, a rate limit) is masked for ever, and because this container
# re-runs issuance on every start, it prints the mask on every start too — the [acme] lines below stop
# naming the cause. It cannot heal itself: issue() only calls createDomainKey when the requested keylength
# differs from Le_Keylength in the domain conf, and that is written ONLY on a successful key creation.
# NOT --force (it re-issues on every restart and burns Let's Encrypt's 5-duplicates-per-week): drop the
# entry. Scoped to the _ecc entry our --keylength ec-256 issuance uses, and only when it holds no usable
# cert. The twin of swg-netctl's _acme_clear_unusable() and install-host.sh's acme_clear_unusable().
# The acme state dir is a MOUNTED VOLUME, so this also clears a trap left by an older image.
acme_clear_unusable(){
  local d="$ACME_CFG/${PANEL_DOMAIN}_ecc"
  [ -d "$d" ] || return 0
  if [ -s "$d/fullchain.cer" ] && head -1 "$d/${PANEL_DOMAIN}.cer" 2>/dev/null | grep -q 'BEGIN CERTIFICATE'; then return 0; fi
  log "clearing a failed acme entry for $PANEL_DOMAIN (a domain key with no certificate) — it would mask every re-issue with \"Domain key exists\""
  rm -rf "$d"; }
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
# cert_is_selfsigned() and cert_covers_host() are defined at the top of this file (shared with the sub-cert path).
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
      acme_clear_unusable        # a previous failure's leftover would refuse this order too
      # capture acme's full output so a failure shows WHY in 'docker logs' (don't hide it in /dev/null)
      if _out="$(acme --issue -d "$PANEL_DOMAIN" --standalone --server letsencrypt --keylength ec-256 2>&1)" || acme_has_cert; then
        acme_install; log "Let's Encrypt cert installed"
      else
        printf '%s\n' "$_out" | sed 's/^/[acme] /'
        log "WARNING: letsencrypt issuance FAILED (see [acme] lines above). HTTP-01 needs port 80 reachable from the internet and breaks behind Cloudflare's proxy — use TLS=cloudflare (DNS-01) or cf15. Falling back to self-signed."
        acme_hint "$_out"; acme_clear_unusable; selfsigned
      fi ;;
    letsencrypt-ip)
      [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
      log "issuing a short-lived (~6 day) Let's Encrypt IP certificate for $PANEL_DOMAIN (HTTP-01 standalone on :80)…"
      acme_clear_unusable        # a previous failure's leftover would refuse this order too
      # IP certs must use the shortlived profile; --days 3 → the 12h renew loop re-issues ~2 days in (≈4-day buffer)
      if _out="$(acme --issue -d "$PANEL_DOMAIN" --standalone --server letsencrypt --keylength ec-256 --certificate-profile shortlived --days 3 2>&1)" || acme_has_cert; then
        acme_install; log "Let's Encrypt IP cert installed (short-lived; auto-renews every 12h)"
      else
        printf '%s\n' "$_out" | sed 's/^/[acme] /'
        log "WARNING: letsencrypt-ip issuance FAILED (see [acme] lines above). Needs port 80 reachable, a PUBLIC IP, and a direct hit (not behind Cloudflare's proxy). Falling back to self-signed."
        acme_hint "$_out"; acme_clear_unusable; selfsigned
      fi ;;
    cloudflare)
      [ -n "${CF_TOKEN:-}" ] || { log "WARNING: TLS=cloudflare but CF_TOKEN unset — falling back to self-signed"; selfsigned; }
      if [ -n "${CF_TOKEN:-}" ]; then
        [ -n "${ACME_EMAIL:-}" ] && acme --register-account -m "$ACME_EMAIL" --server letsencrypt >/dev/null 2>&1 || true
        log "issuing $PANEL_DOMAIN via Let's Encrypt (DNS-01 through Cloudflare)…"
        acme_clear_unusable      # a previous failure's leftover would refuse this order too
        if _out="$(CF_Token="$CF_TOKEN" acme --issue -d "$PANEL_DOMAIN" --dns dns_cf --server letsencrypt --keylength ec-256 2>&1)" || acme_has_cert; then
          acme_install; log "Cloudflare DNS-01 cert installed"
        else
          printf '%s\n' "$_out" | sed 's/^/[acme] /'
          log "WARNING: cloudflare (DNS-01) issuance FAILED (see [acme] lines above) — check the token has Zone:DNS:Edit + Zone:Read and that $PANEL_DOMAIN is on that account. Falling back to self-signed."
          acme_hint "$_out"; acme_clear_unusable; selfsigned
        fi
      fi ;;
    cf15)
      [ -n "${CF_ORIGIN_TOKEN:-}" ] || { log "WARNING: TLS=cf15 but CF_ORIGIN_TOKEN unset — falling back to self-signed"; selfsigned; }
      if [ -n "${CF_ORIGIN_TOKEN:-}" ]; then
        log "requesting a 15-year Cloudflare Origin certificate for $PANEL_DOMAIN…"
        _cferr="$(mktemp 2>/dev/null || echo /tmp/cf15.err)"
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
if d.get("success"):
    sys.stdout.write(d["result"]["certificate"])
else:
    # Say WHAT Cloudflare objected to. Exiting mute left "cf15 request failed" and three things to guess
    # between (wrong token, wrong scope, zone not on this account); the bare-metal path has always printed
    # this, so the container was strictly worse at the same job.
    for _e in (d.get("errors") or [{"message": "unknown error"}]):
        sys.stderr.write("%s (code %s)\n" % (_e.get("message", "?"), _e.get("code", "?")))
    sys.exit(1)
PY
)" 2>"$_cferr" && [ -n "$cert" ] && { printf '%s\n' "$cert" > "$SWG_PANEL_TLS_CERT"; printf '%s\n' "$key" > "$SWG_PANEL_TLS_KEY"; log "Cloudflare Origin cert installed (15y) — valid only behind Cloudflare's proxy"; } \
          || { log "WARNING: cf15 request failed — Cloudflare's response:"
               while IFS= read -r _l; do [ -n "$_l" ] && log "  [cf] $_l"; done < "$_cferr"
               log "  the token needs Zone → SSL and Certificates → Edit, and $PANEL_DOMAIN must be on that account"
               log "  falling back to self-signed"; selfsigned; }
        rm -f "$_cferr" 2>/dev/null || true
      fi ;;
    *) log "unknown TLS='$TLS' — using self-signed"; selfsigned ;;
  esac
  [ -n "${SWG_PANEL_TLS_KEY:-}" ] && [ -f "${SWG_PANEL_TLS_KEY:-/nonexistent}" ] && chmod 600 "$SWG_PANEL_TLS_KEY" 2>/dev/null || true
fi

# DRY-RUN: verify the NEW params can produce a usable cert (the risky, failure-prone step) WITHOUT starting the
# server — so the panel can prove a scheme/port/domain change will work BEFORE it recreates the live container.
# The cert we just issued lands in the mounted acme/tls volume, so the real recreate reuses it (no second issuance).
# Exit 0 = the change is safe to apply; non-zero = abort (the caller keeps the old container running untouched).
if [ "${DRY_RUN:-}" = 1 ]; then
  case "${TLS:-selfsigned}" in
    none) log "dry-run OK: reverse-proxy (plain HTTP) — no certificate needed"; exit 0 ;;
    selfsigned|"")
      { [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -f "$SWG_PANEL_TLS_CERT" ] && cert_covers_domain "$SWG_PANEL_TLS_CERT"; } \
        && { log "dry-run OK: self-signed certificate for $PANEL_DOMAIN"; exit 0; }
      log "dry-run FAILED: couldn't produce a self-signed certificate for $PANEL_DOMAIN"; exit 3 ;;
    *)
      { [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -f "$SWG_PANEL_TLS_CERT" ] && ! cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && cert_covers_domain "$SWG_PANEL_TLS_CERT"; } \
        && { log "dry-run OK: a valid $TLS certificate for $PANEL_DOMAIN is ready"; exit 0; }
      log "dry-run FAILED: no valid certificate for $PANEL_DOMAIN (would serve self-signed / wrong-domain)"; exit 3 ;;
  esac
fi

# 2b) swg-sub's OWN cert (direct-TLS). Issued via issue_sub_cert() defined at the top of this file. Runs in the
#     BACKGROUND (`&`): a fresh DNS-01 issue can take ~60s and blocking the panel boot on it would starve a flip's
#     reachability commit (false auto-revert). The panel serves immediately; swg-sub picks the cert up on its next
#     (re)start. At RUNTIME the panel-managed path is swg-netctl-docker's issue-cert verb → `entrypoint.sh sub-cert`.
# The sub's domain is PANEL-MANAGED (access.sub.url in panel-settings.json), so prefer that over the static install
# env — otherwise a restart would re-issue for the env default and clobber a cert the UI issued for a different sub
# host. Env stays the bootstrap for a first boot before any sub address is saved.
_sub_dom_cfg="$(python3 - /var/lib/swg-panel/panel-settings.json 2>/dev/null <<'PY'
import json,sys
from urllib.parse import urlparse
try:
    u = (((json.load(open(sys.argv[1])).get("access") or {}).get("sub") or {}).get("url") or "")
    print(urlparse(u).hostname or "")
except Exception:
    print("")
PY
)"
[ -n "$_sub_dom_cfg" ] && SUB_DOMAIN="$_sub_dom_cfg"
if [ "${TLS:-selfsigned}" != none ] && [ -n "${SUB_DOMAIN:-}" ]; then ( issue_sub_cert ) & fi

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
    # Record the outcome where the PANEL can read it. A loud log line is only ever seen by someone who goes
    # looking in `docker logs`; renewal can then fail hourly for weeks while the console shows a healthy
    # certificate, because the panel's own watch is an EXPIRY watch and says nothing until 14 days out.
    #
    # ⚠️ HEALTH IS ABOUT *THIS PANEL'S* CERTIFICATE — NEVER --cron's EXIT CODE. `acme.sh --cron` walks every
    # entry in the store and fails if ANY of them fails, and the store is a mounted volume that a convert
    # carries over wholesale from the old host: observed with SEVEN unrelated domains in it, none of which
    # resolve here any more, so --cron returned non-zero for ever while our own certificate was renewing
    # perfectly well. Keying the status file to that exit code would have pinned a permanent false alarm to
    # the operator's screen — worse than the silence it was meant to fix.
    #
    # Two things can be wrong with OUR certificate, and neither needs acme's opinion of anyone else's:
    #   · the run reported an error naming our own domain, or
    #   · the certificate is inside its renewal window and STILL old — renewal had its chance and did not take.
    ( while :; do
        out="$(acme --cron 2>&1)" || true
        _bad=no; _why=""
        if printf '%s' "$out" | grep -qiE "error.*(renew|issu).*${PANEL_DOMAIN}"; then
          _bad=yes; _why="$(printf '%s' "$out" | grep -iE "error.*${PANEL_DOMAIN}" | tail -1)"
        else
          _left="$(cert_days_left "$SWG_PANEL_TLS_CERT")"
          if [ -n "$_left" ] && [ "$_left" -le 20 ]; then
            _bad=yes; _why="certificate has ${_left} day(s) left and has not been renewed"
          fi
        fi
        if [ "$_bad" = no ]; then
          printf 'ok %s\n' "$(date +%s)" > "$ACME_CFG/.renew-status" 2>/dev/null || true
          sleep 43200
        else
          # keep the FIRST failure time across iterations — "failing since" is the fact worth having
          _since="$(sed -n 's/^failing \([0-9]*\).*/\1/p' "$ACME_CFG/.renew-status" 2>/dev/null | head -1)"
          printf 'failing %s %s\n' "${_since:-$(date +%s)}" "$_why" > "$ACME_CFG/.renew-status" 2>/dev/null || true
          log "WARNING: TLS auto-renewal failed for $PANEL_DOMAIN — retrying in 1h. last: $_why"; sleep 3600
        fi
      done ) &
    log "TLS auto-renewal enabled (acme.sh --cron every 12h; 1h retry on failure; reload via SIGHUP)" ;;
esac

log "starting swg-panel-server on ${SWG_PANEL_HOST:-0.0.0.0}:${SWG_PANEL_PORT:-8443}"
exec "${SWG_PANEL_BIN:-/opt/swg-panel/swg-panel-server}"
