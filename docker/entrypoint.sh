#!/bin/sh
# swg-panel container entrypoint. Materialises a login + TLS cert + a starter
# fleet.json from env / mounted volumes, then execs the broker. Mirrors the
# standalone bare-metal install, driven by env instead of the installer.
set -eu

log() { printf '\033[0;36m[entrypoint]\033[0m %s\n' "$*"; }
# The renewal loop's outcome also goes to the panel's own log file, as `acme: …` lines, so Settings → Logs shows it under
# the Panel (docs/LOGS-PLAN.md §23.6) — the container log alone is not where the viewer reads. At the panel's level (its
# base level; Off: nothing — the panel deleted the file), into the file whether or not it is there yet: the panel writes it
# from its first kept line on, so after Off → Warnings, or a rotation, a quiet panel dropped the renewal warning for days,
# and at Errors the hourly Info line still went in (1.8.9 qualification DN-10).
panel_log(){   # <letter E/W/I> <text>
  local f=/var/lib/swg-panel/log/swg-panel.log lvl
  lvl="$(sed -n 's/.*"log_level"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' /var/lib/swg-panel/panel-settings.json 2>/dev/null | sed -n 1p)"
  case "$lvl:$1" in off:*|error:[WI]|warning:I) return 0;; esac
  mkdir -p "${f%/*}" 2>/dev/null || true; printf '%s %s acme: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >> "$f" 2>/dev/null || true
}

# ─────────────────────── swg-sub certificate (defined up front) ───────────────────────
# Defined here so the `sub-cert <domain>` RUNTIME subcommand — swg-netctl-docker calls `entrypoint.sh sub-cert
# <domain>` when the panel's subscription address changes (a DIFFERENT host the panel cert doesn't cover) — can
# issue swg-sub's cert WITHOUT running the whole panel bootstrap. The boot path below calls the same issue_sub_cert.
ACME="${ACME_BIN:-/opt/acme.sh/acme.sh}"; ACME_CFG="${ACME_CONFIG:-/etc/swg-panel/acme}"
acme(){ "$ACME" --config-home "$ACME_CFG" "$@"; }
cert_is_selfsigned(){ local i s
  # strip openssl's `issuer=`/`subject=` labels — else the two strings ALWAYS differ and self-signed is never seen.
  i="$(openssl x509 -in "$1" -noout -issuer 2>/dev/null | sed 's/^issuer= *//')"
  s="$(openssl x509 -in "$1" -noout -subject 2>/dev/null | sed 's/^subject= *//')"
  [ -n "$i" ] && [ "$i" = "$s" ]; }
# An IP address in one spelling (IPv6 as Python prints it), or nothing when $1 is not one.
ip_canon(){ python3 -c 'import ipaddress, sys
try: print(ipaddress.ip_address(sys.argv[1].strip("[]")))
except ValueError: pass' "$1" 2>/dev/null || true; }
# Does cert $1 cover hostname $2 — an exact SAN/CN, or a single-label *.wildcard (so *.example.com covers
# sub.example.com but not a.b.example.com)? An IP address is covered by an `IP Address:` SAN only: a Let's Encrypt IP
# certificate has no DNS name at all, and reading DNS alone sent an IP panel's sub on the same IP to the Let's Encrypt
# branch below, whose --install-cert took the panel's own acme entry (S9f; swg-netctl learned the same in 1.8.8).
cert_covers_host(){ local host="$2" dns base pre ip hip
  hip="$(ip_canon "$host")"
  if [ -n "$hip" ]; then
    for ip in $(openssl x509 -in "$1" -noout -text 2>/dev/null | grep -oE 'IP Address:[^,[:space:]]+' | cut -d: -f2-); do
      [ "$(ip_canon "$ip")" = "$hip" ] && return 0
    done
    # …or a DNS SAN spelling the address: the self-signed sub certificate an earlier image wrote (review F1) — refused
    # there, it was minted again on every start, a new key each time. All of it: an IPv6 one has colons of its own
    for dns in $(openssl x509 -in "$1" -noout -text 2>/dev/null | grep -oE 'DNS:[^,[:space:]]+' | cut -d: -f2-); do
      [ "$dns" = "$host" ] || [ "$(ip_canon "$dns")" = "$hip" ] && return 0
    done
    return 1
  fi
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
# Why a certificate FILE is overdue for renewal, or nothing when it is not (or cannot be read — never a fault). One that
# lives 10 days or less (a Let's Encrypt IP / shortlived one, ~6.7 days) is overdue past 2/3 of its life, the panel's
# _SHORT_LIVED_S rule: a fixed "20 days left" read every IP certificate as failing from the day it was issued (S9f).
# A longer one is overdue at 20 days left (a 90-day certificate renews at 30).
cert_overdue(){
  local nb na now life left
  [ -s "${1:-}" ] || return 0
  nb="$(date -d "$(openssl x509 -in "$1" -noout -startdate 2>/dev/null | cut -d= -f2)" +%s 2>/dev/null)" || return 0
  na="$(date -d "$(openssl x509 -in "$1" -noout -enddate 2>/dev/null | cut -d= -f2)" +%s 2>/dev/null)" || return 0
  [ -n "$nb" ] && [ -n "$na" ] || return 0
  now="$(date +%s)"; life=$((na - nb)); left=$((na - now))
  if [ "$life" -gt 0 ] && [ "$life" -le 864000 ]; then
    [ $((left * 3)) -lt "$life" ] && echo "certificate has $((left / 3600)) hour(s) left of its $(( (life + 43200) / 86400 ))-day life and has not been renewed"
  elif [ $((left / 86400)) -le 20 ]; then
    echo "certificate has $((left / 86400)) day(s) left and has not been renewed"
  fi
  return 0
}
SUB_TLS_DIR="${SUB_TLS_DIR:-/etc/swg-sub/tls}"; SC="$SUB_TLS_DIR/fullchain.pem"; SK="$SUB_TLS_DIR/key.pem"
sub_selfsigned(){ local san="DNS:$SUB_DOMAIN"
  [ -n "$(ip_canon "$SUB_DOMAIN")" ] && san="IP:$(ip_canon "$SUB_DOMAIN")"   # an address is an IP SAN, as the panel's own
  mkdir -p "$SUB_TLS_DIR"
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$SK" -out "$SC" \
    -subj "/CN=$SUB_DOMAIN" -addext "subjectAltName=$san" >/dev/null 2>&1
  log "swg-sub: generated self-signed cert (CN=$SUB_DOMAIN)"; }
# The file an acme entry installs its certificate to ("" when there is no such entry).
acme_target(){ sed -n "s/^Le_RealFullChainPath='\{0,1\}\([^']*\).*/\1/p" "$ACME_CFG/${1}_ecc/${1}.conf" 2>/dev/null | head -1; }
# Is $1's acme entry the PANEL's — its name, or an entry installing to the panel's file? acme.sh keeps ONE install target
# per entry, so an --install-cert for the sub on it re-points every later renewal at the sub's directory (no reload), and
# the panel serves its last certificate until it expires: a letsencrypt-ip panel at about day 6.7 (S9f, seen live).
acme_entry_is_panels(){
  case "${TLS:-}" in letsencrypt|letsencrypt-ip|cloudflare) ;; *) return 1 ;; esac
  [ "$1" = "${PANEL_DOMAIN:-}" ] && return 0
  [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ "$(acme_target "$1")" = "$SWG_PANEL_TLS_CERT" ]; }
# Is the sub's present pair the one to keep beside a SELF-SIGNED panel certificate that covers its host? It covers the
# host and is the kind this mode keeps: its own self-signed one in selfsigned mode (a Let's Encrypt copy left from an
# earlier mode is never renewed there), a real one in a CA mode (the panel's is then a failed issuance's placeholder).
# Its key must be the certificate's: a start killed between the copy's two `cp`s, or a lost key, takes the copy again —
# nothing else would repair a pair swg-sub cannot serve.
sub_pair_kept(){ local p
  [ -s "$SC" ] && cert_covers_host "$SC" "$SUB_DOMAIN" || return 1
  p="$(openssl x509 -in "$SC" -noout -pubkey 2>/dev/null)"
  [ -n "$p" ] && [ "$p" = "$(openssl pkey -in "$SK" -pubout 2>/dev/null)" ] || return 1
  if [ "${TLS:-selfsigned}" = selfsigned ]; then cert_is_selfsigned "$SC"; else ! cert_is_selfsigned "$SC"; fi; }
# A page host that changed leaves the old host's acme entry installing to the page's files: acme renews it on its own
# schedule — DNS-01 always, HTTP-01 while the old name still points here — and writes the OLD host's certificate over the
# page, which nothing puts back (sub_follow_panel leaves a page with an entry of its own alone) until the next start or the
# new host's renewal, up to ~60 days. Bare metal drops the old name (swg-netctl drop-cert); here, once the page holds a
# real certificate for its host, an entry installing to $SC for a host that is neither the page's nor the panel's is
# removed — never before (a failed or mistyped new host keeps the old entry to go back to) and only for a host known for
# certain, SUB_HOST_SURE: an unreadable panel-settings.json leaves SUB_DOMAIN at the env default, and the page's real
# entry would look stale (review F3/F4).
sub_prune_stale(){ local conf d dl sl pl
  sl="$(printf '%s' "${SUB_DOMAIN:-}" | tr '[:upper:]' '[:lower:]')"; pl="$(printf '%s' "${PANEL_DOMAIN:-}" | tr '[:upper:]' '[:lower:]')"
  [ -n "$sl" ] || return 0
  for conf in "$ACME_CFG"/*/*.conf; do
    [ -f "$conf" ] || continue
    [ "$(sed -n "s/^Le_RealFullChainPath='\{0,1\}\([^']*\).*/\1/p" "$conf" | head -1)" = "$SC" ] || continue
    d="$(sed -n "s/^Le_Domain='\{0,1\}\([^']*\).*/\1/p" "$conf" | head -1)"; dl="$(printf '%s' "$d" | tr '[:upper:]' '[:lower:]')"
    [ -n "$d" ] && [ "$dl" != "$sl" ] && [ "$dl" != "$pl" ] || continue
    log "swg-sub: removing stale acme entry $d (it installs to the subscription page's certificate; the page is $SUB_DOMAIN now)"
    acme --remove -d "$d" --ecc >/dev/null 2>&1 || true
    rm -rf "$(dirname "$conf")"
  done; }
# Ensure swg-sub's cert for $SUB_DOMAIN. Rule: if the panel's OWN cert already covers the sub host (same domain, or a
# SAN/wildcard) reuse it — no second issuance — unless it is self-signed and the sub's present pair is kept (above); else
# issue a SEPARATE cert (own key). Never blocks the caller fatally.
# ⚠️ A self-signed panel certificate covers its sub on an IP since IP SANs count (S9f), and without the keep the update
# from 1.8.10 swapped the sub's own self-signed pair for the panel's — a new certificate a browser that had accepted the
# page warned about again, for nothing (nightly docker-pristine, 10-25..10-28).
issue_sub_cert(){ set +e
  local pc=
  mkdir -p "$SUB_TLS_DIR"
  [ -n "${SWG_PANEL_TLS_CERT:-}" ] && [ -s "$SWG_PANEL_TLS_CERT" ] && [ -s "${SWG_PANEL_TLS_KEY:-/nonexistent}" ] \
    && cert_covers_host "$SWG_PANEL_TLS_CERT" "$SUB_DOMAIN" && pc=1
  if [ -n "$pc" ] && cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && sub_pair_kept; then
    log "swg-sub: reusing present cert for $SUB_DOMAIN"
  elif [ -n "$pc" ]; then
    cp "$SWG_PANEL_TLS_CERT" "$SC"; cp "$SWG_PANEL_TLS_KEY" "$SK"
    log "swg-sub: panel certificate covers $SUB_DOMAIN — reusing it for the subscription page"
  elif [ -s "$SC" ] && { [ "${TLS:-selfsigned}" = selfsigned ] || ! cert_is_selfsigned "$SC"; } \
       && cert_covers_host "$SC" "$SUB_DOMAIN"; then
    log "swg-sub: reusing present cert for $SUB_DOMAIN"
  elif acme_entry_is_panels "$SUB_DOMAIN"; then
    # the panel's own entry: read its certificate, never install onto it (the panel's file not usable yet, or not covering)
    _ed="$ACME_CFG/${SUB_DOMAIN}_ecc"
    if [ -s "$_ed/fullchain.cer" ] && [ -s "$_ed/${SUB_DOMAIN}.key" ] && head -1 "$_ed/${SUB_DOMAIN}.cer" 2>/dev/null | grep -q 'BEGIN CERTIFICATE'; then
      cp "$_ed/${SUB_DOMAIN}.key" "$SK"; cp "$_ed/fullchain.cer" "$SC"
      log "swg-sub: $SUB_DOMAIN is the panel's own certificate entry — copied its certificate for the subscription page"
    else sub_selfsigned; fi
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
  [ -n "${SUB_HOST_SURE:-}" ] && [ -s "$SC" ] && ! cert_is_selfsigned "$SC" && cert_covers_host "$SC" "$SUB_DOMAIN" && sub_prune_stale
  [ -f "$SK" ] && chmod 600 "$SK" 2>/dev/null || true
  return 0; }
# Runtime subcommand (panel-managed): re-issue swg-sub's cert for a specific domain, then exit — no panel bootstrap.
if [ "${1:-}" = "sub-cert" ]; then
  SUB_DOMAIN="${2:-${SUB_DOMAIN:-}}"; [ -n "${2:-}" ] && SUB_HOST_SURE=1   # the panel names the page's host
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
  # ⚠️ A PLACEHOLDER IS NEVER A PASSWORD. .env holds "(preserved)" once the panel holds its login (and after a re-install
  # or a convert: converted-login-preserved), so a login file lost AFTER that would have become a login whose password
  # is the placeholder. Refused: no login is minted from it, and the panel does not start without one.
  case "${PANEL_PASSWORD:-}" in "(preserved)"|converted-login-preserved|unused-on-node-only)
    log "ERROR: the login file ($SWG_PANEL_AUTH) is missing and .env holds no password (PANEL_PASSWORD is a placeholder) — refusing to start without a login. Re-run the installer (it keeps your data and sets a new login), or put a password in PANEL_PASSWORD in .env and recreate the container."
    exit 1;;
  esac
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
# Re-assert the panel entry's install target on a start that reuses the certificate on disk. Something that ran
# --install-cert on our entry (an older image's sub step did, S9f) left every renewal going elsewhere, and that start
# never called acme_install, so nothing put it back. The store is this container's own volume: no other tool's target.
acme_reassert(){ local e="$ACME_CFG/${PANEL_DOMAIN}_ecc"
  case "${TLS:-}" in letsencrypt|letsencrypt-ip|cloudflare) ;; *) return 0 ;; esac
  acme_has_cert || return 0
  # only when the panel serves the key of the _ecc entry acme_install installs: a certificate the operator mounted over
  # it stays theirs (review F6), and an RSA entry from an older store, with no _ecc key, is not re-pointed (review F2)
  cmp -s "$SWG_PANEL_TLS_KEY" "$e/${PANEL_DOMAIN}.key" || return 0
  [ "$(acme_target "$PANEL_DOMAIN")" = "$SWG_PANEL_TLS_CERT" ] && return 0
  log "the acme entry for $PANEL_DOMAIN installs to $(acme_target "$PANEL_DOMAIN" || true), not the panel's certificate — re-pointing it at the panel"
  acme_install; }

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
  acme_reassert
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
#     reachability commit (false auto-revert). The panel serves immediately; swg-sub's first start waits for the panel's
#     serve.json, then for this cert (both waits bounded), so it serves HTTPS from its first listen (1.8.9 qualification
#     U22-1). At RUNTIME the panel-managed path is swg-netctl-docker's issue-cert verb → `entrypoint.sh sub-cert`.
# The sub's domain is PANEL-MANAGED (access.sub.url in panel-settings.json), so prefer that over the static install
# env — otherwise a restart would re-issue for the env default and clobber a cert the UI issued for a different sub
# host. Env stays the bootstrap for a first boot before any sub address is saved.
# Exits 1 when the file is there but cannot be read (its host unknown, not absent); none yet is a first boot's "".
sub_domain_cfg(){ python3 - "${PANEL_SETTINGS:-/var/lib/swg-panel/panel-settings.json}" 2>/dev/null <<'PY'
import json,os,sys
from urllib.parse import urlparse
if not os.path.exists(sys.argv[1]):
    print(""); sys.exit(0)
try:
    u = (((json.load(open(sys.argv[1])).get("access") or {}).get("sub") or {}).get("url") or "")
    print(urlparse(u).hostname or "")
except Exception:
    print("")
    sys.exit(1)
PY
}
_sub_dom_cfg="$(sub_domain_cfg)" && SUB_HOST_SURE=1         # read, or none yet: SUB_DOMAIN below IS the page's host
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

# 4a) A subscription page serving the PANEL's certificate follows its renewals. issue_sub_cert copies it once, at start;
#     the renewal below then reaches only the panel's file, and swg-sub served the old copy until it expired — about day
#     6.7 of an IP certificate, day 90 of a domain one (S9f). Its copy, or its cert for a host the panel's covers, is
#     replaced whenever the panel's differs; swg-sub sees the new files on its own (it watches them).
sub_follow_panel(){ local d f dl
  [ -s "$SC" ] && [ -s "${SWG_PANEL_TLS_CERT:-/nonexistent}" ] && [ -s "${SWG_PANEL_TLS_KEY:-/nonexistent}" ] || return 0
  cmp -s "$SWG_PANEL_TLS_CERT" "$SC" && return 0
  cert_is_selfsigned "$SWG_PANEL_TLS_CERT" && return 0     # a failed issuance's placeholder never replaces the sub's cert
  d="$(sub_domain_cfg)"; d="${d:-${SUB_DOMAIN:-}}"; dl="$(printf '%s' "$d" | tr '[:upper:]' '[:lower:]')"
  for f in "$ACME_CFG"/*/*.conf; do                         # the sub has a renewer of its own: its entry installs here
    [ -f "$f" ] && [ "$(sed -n "s/^Le_RealFullChainPath='\{0,1\}\([^']*\).*/\1/p" "$f" | sed -n 1p)" = "$SC" ] \
      && { [ -z "$d" ] || [ "$(sed -n "s/^Le_Domain='\{0,1\}\([^']*\).*/\1/p" "$f" | sed -n 1p | tr '[:upper:]' '[:lower:]')" = "$dl" ]; } \
      && return 0
  done      # (review F3: the two overwrote each other on alternate renewals) — for the sub's host now, not one it had
  cmp -s "$SWG_PANEL_TLS_KEY" "$SK" || { [ -n "$d" ] && cert_covers_host "$SWG_PANEL_TLS_CERT" "$d"; } || return 0
  cp "$SWG_PANEL_TLS_KEY" "$SK.new" && chmod 600 "$SK.new" && cp "$SWG_PANEL_TLS_CERT" "$SC.new" \
    && mv -f "$SK.new" "$SK" && mv -f "$SC.new" "$SC" \
    && log "swg-sub: the panel's certificate changed — the subscription page's copy follows it" \
    || log "WARNING: could not copy the panel's renewed certificate for the subscription page"
}
# Why THIS panel's certificate renewal is failing after a `--cron` run whose output is $1 — or nothing when it is not.
# Two things can be wrong with OUR certificate, and neither needs acme's opinion of anyone else's (see the loop below):
# the run reported an error naming our own domain, or the certificate is overdue (cert_overdue) and still old. When the
# installer could not publish :80 (something else held it, .port80-held), the reason says who, and the way out (S9f).
renew_why(){ local why
  if printf '%s' "$1" | grep -qiE "error.*(renew|issu).*${PANEL_DOMAIN}"; then
    why="$(printf '%s' "$1" | grep -iE "error.*${PANEL_DOMAIN}" | tail -1)"
  else
    why="$(cert_overdue "$SWG_PANEL_TLS_CERT")"
  fi
  [ -n "$why" ] || return 0
  if [ -s "$ACME_CFG/.port80-held" ] && [ "${TLS:-}" != cloudflare ]; then
    why="$why — the installer found host port 80 held by $(head -c 64 "$ACME_CFG/.port80-held" | tr -d '\n') and did not publish it, so Let's Encrypt may not reach this panel: if that is still so, free port 80 and re-run the installer$([ "${TLS:-}" = letsencrypt ] && echo ", or switch to Cloudflare DNS-01" || true)"
  fi
  printf '%s\n' "$why"; }
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
        sub_follow_panel || true
        _why="$(renew_why "$out")"
        if [ -z "$_why" ]; then
          printf 'ok %s\n' "$(date +%s)" > "$ACME_CFG/.renew-status" 2>/dev/null || true
          panel_log I "renewal check for $PANEL_DOMAIN ok ($(cert_days_left "$SWG_PANEL_TLS_CERT") day(s) left)"
          sleep 43200
        else
          # keep the FIRST failure time across iterations — "failing since" is the fact worth having
          _since="$(sed -n 's/^failing \([0-9]*\).*/\1/p' "$ACME_CFG/.renew-status" 2>/dev/null | head -1)"
          printf 'failing %s %s\n' "${_since:-$(date +%s)}" "$_why" > "$ACME_CFG/.renew-status" 2>/dev/null || true
          log "WARNING: TLS auto-renewal failed for $PANEL_DOMAIN — retrying in 1h. last: $_why"
          panel_log W "renewal failed for $PANEL_DOMAIN — retrying in 1h: $_why"; sleep 3600
        fi
      done ) &
    log "TLS auto-renewal enabled (acme.sh --cron every 12h; 1h retry on failure; reload via SIGHUP)" ;;
esac

log "starting swg-panel-server on ${SWG_PANEL_HOST:-0.0.0.0}:${SWG_PANEL_PORT:-8443}"
exec "${SWG_PANEL_BIN:-/opt/swg-panel/swg-panel-server}"
