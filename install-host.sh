#!/usr/bin/env bash
# install-host.sh — set up the swg-panel host (server + UI + collector + receiver).
#
# Two roles, chosen by ROLE below (or asked): host (panel only) or host+node.
#   single                         everything on this one box; this host is the only node
#   multi + HOST_HAS_WG=yes        panel here AND wg/awg here, plus remote nodes
#   multi + HOST_HAS_WG=no         panel here, wg/awg only on remote nodes
#
# Fill the CONFIG block to run unattended, or leave blanks to be prompted.
# Run as root. Use --dry-run to render every file under ./dryrun and execute nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
METHOD="${METHOD:-baremetal}"          # baremetal (systemd). For Docker, use docker-compose instead.
ROLE="${ROLE:-}"                       # host (panel only) | host+node (panel + this box is also an entry server)
HOST_NODE_NAME="${HOST_NODE_NAME:-}"   # node name for THIS box (host+node only)
HOST_ENDPOINT_IP="${HOST_ENDPOINT_IP:-}" # public IP clients dial for this box's wg (host+node only)
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = pick from detected; host+node only)

PANEL_DOMAIN="${PANEL_DOMAIN:-}"       # domain or IP for the URL/cert; blank = this host's IP (fine for standalone)
STORE_CONFIGS="${STORE_CONFIGS:-false}"

SERVE_MODE="${SERVE_MODE:-}"           # standalone (self-contained: own TLS+login, no nginx) | nginx  (blank = ask)
# TLS — how to obtain the certificate:
TLS_MODE="${TLS_MODE:-}"               # selfsigned | letsencrypt | cloudflare | manual | none  (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare: API token with Zone:DNS:Edit
CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-}"     # cloudflare: optional account id
CERT_FULLCHAIN="${CERT_FULLCHAIN:-}"   # manual: path to fullchain.pem (also where acme installs it)
CERT_KEY="${CERT_KEY:-}"               # manual: path to private key.pem
BASIC_USER="${BASIC_USER:-admin}"
BASIC_PASS="${BASIC_PASS:-}"           # blank -> random, printed at the end

# Remote nodes are NOT listed here — add them in the panel's Nodes screen, which
# issues a one-time token + an install-node.sh command to run on each server.

# paths / identities (defaults are sane)
PANEL_DIR="${PANEL_DIR:-/opt/swg-panel}"
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
ETC_DIR="${ETC_DIR:-/etc/swg-panel}"
STATE_DIR="${STATE_DIR:-/var/lib/swg-panel}"
STATS_DIR="${STATS_DIR:-/var/www/wgstats}"
PANEL_USER="${PANEL_USER:-swgpanel}"
PORT="${PORT:-}"
TLS_DIR="${TLS_DIR:-/etc/swg-panel/tls}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/www/acme}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PALETTE=("#34d399" "#22d3ee" "#c084e8" "#f0913c" "#e8c04b" "#60a5fa" "#f0596b")

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '0;36')▸$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '0;33')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
writef(){ # writef <abs_path> <mode>   (content on stdin)
  local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"
  chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }

ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p${d:+ [$d]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi
  read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true
  v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

# ───────────────────────── wg/awg detection ─────────────────────────
declare -A IF_CMD IF_CONF
detect_wg(){
  IF_CMD=(); IF_CONF=()
  local f n
  for f in /etc/amnezia/amneziawg/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"; done
  for f in /etc/wireguard/*.conf;        do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg;  IF_CONF[$n]="$f"; done
}
choose_ifaces(){ # populates SELECTED[] (names); installs wg/awg if absent
  detect_wg
  if [ "${#IF_CMD[@]}" -eq 0 ]; then
    warn "No WireGuard/AmneziaWG configs found in /etc/wireguard or /etc/amnezia/amneziawg."
    local doit; ask_yn "Install now?" y doit _ans_inst; doit="$_ans_inst"
    if [ "$doit" = yes ]; then install_wg; detect_wg; fi
    [ "${#IF_CMD[@]}" -eq 0 ] && die "Still no interfaces. Create one, then re-run (or set MANAGE_IFACES)."
  fi
  local names=("${!IF_CMD[@]}")
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    echo "  Detected interfaces:"; local i=1; for n in "${names[@]}"; do echo "    $i) $n (${IF_CMD[$n]}) ${IF_CONF[$n]}"; i=$((i+1)); done
    local pick; read -rp "  Manage which? (comma indices, or 'all'): " pick </dev/tty || true; pick="${pick:-all}"
    if [ "$pick" = all ]; then SELECTED=("${names[@]}"); else
      SELECTED=(); IFS=',' read -ra idx <<< "$pick"; for j in "${idx[@]}"; do j="${j// /}"; [ -n "$j" ] && SELECTED+=("${names[$((j-1))]}"); done
    fi
  fi
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }; done
  ok "Managing: ${SELECTED[*]}"
}
install_wg(){
  local kind; read -rp "  Install (a)mneziawg or (w)ireguard? [a]: " kind </dev/tty || true; kind="${kind:-a}"
  if [ "$kind" = w ]; then run apt-get update -qq; run apt-get install -y wireguard;
  else run apt-get update -qq; run apt-get install -y software-properties-common;
       run add-apt-repository -y ppa:amnezia/ppa; run apt-get update -qq; run apt-get install -y amneziawg; fi
}

# ───────────────────────── prompts ─────────────────────────
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

ask "Role: host (panel only) or host+node (panel + this box is also an entry server)?" "host" ROLE
case "$ROLE" in host|host+node) ;; node) die "for a node-only box run install-node.sh, not this script";; *) die "ROLE must be 'host' or 'host+node'";; esac
HOST_HAS_WG=no; [ "$ROLE" = "host+node" ] && HOST_HAS_WG=yes

declare -a SELECTED
if [ "$HOST_HAS_WG" = yes ]; then
  ask "Node name for THIS box" "$(hostname -s 2>/dev/null || hostname)" HOST_NODE_NAME
  ask "Public IP clients dial for THIS box" "" HOST_ENDPOINT_IP
  info "Checking wg/awg on this host…"; choose_ifaces
fi
ask "Serve mode: standalone (self-contained, no nginx) or nginx?" "standalone" SERVE_MODE
case "$SERVE_MODE" in standalone|nginx) ;; *) die "SERVE_MODE must be standalone or nginx";; esac
[ -z "$PORT" ] && { [ "$SERVE_MODE" = standalone ] && PORT=8443 || PORT=8088; }
[ "$SERVE_MODE" = standalone ] && ask "Public HTTPS port for the panel" "$PORT" PORT
DEF_DOM="_"
if [ "$SERVE_MODE" = standalone ]; then
  DEF_DOM="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  [ -z "$DEF_DOM" ] && DEF_DOM="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  [ -z "$DEF_DOM" ] && DEF_DOM="_"
fi
ask "Panel domain or IP (URL + certificate)" "$DEF_DOM" PANEL_DOMAIN
[ -z "$TLS_MODE" ] && [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] && TLS_MODE=manual
DEF_TLS="letsencrypt"; [ "$SERVE_MODE" = standalone ] && DEF_TLS="selfsigned"
ask "TLS cert: selfsigned, letsencrypt, cloudflare, manual or none?" "$DEF_TLS" TLS_MODE
case "$TLS_MODE" in
  selfsigned) ;;
  cloudflare)  ask "Cloudflare API token (Zone:DNS:Edit)" "" CF_TOKEN; ask "ACME account email" "" ACME_EMAIL;;
  letsencrypt) ask "ACME account email" "" ACME_EMAIL;;
  manual)      ask "Path to fullchain.pem" "" CERT_FULLCHAIN; ask "Path to private key.pem" "" CERT_KEY;;
  none) ;;
  *) die "TLS_MODE must be selfsigned|letsencrypt|cloudflare|manual|none";;
esac
if [ "$TLS_MODE" = letsencrypt ] || [ "$TLS_MODE" = cloudflare ]; then
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) : ;; *) die "TLS_MODE=$TLS_MODE needs a real domain in PANEL_DOMAIN (not an IP)";; esac
  case "$PANEL_DOMAIN" in *.*) : ;; *) die "PANEL_DOMAIN must be a FQDN for $TLS_MODE";; esac
fi
if [ "$SERVE_MODE" = standalone ] && { [ -z "$PANEL_DOMAIN" ] || [ "$PANEL_DOMAIN" = "_" ]; }; then
  PANEL_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  [ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
fi
[ -z "$BASIC_PASS" ] && BASIC_PASS="$(head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16)"

echo; info "Plan: method=$METHOD role=$ROLE store_configs=$STORE_CONFIGS"

# ───────────────────────── users / dirs ─────────────────────────
info "Users, groups, directories"
run groupadd -f swg
id "$PANEL_USER" >/dev/null 2>&1 || run useradd -r -g swg -d "$STATE_DIR" -s /usr/sbin/nologin "$PANEL_USER"
run usermod -d "$STATE_DIR" -g swg "$PANEL_USER"
for d in "$PANEL_DIR" "$ETC_DIR" "$STATE_DIR" "$STATS_DIR"; do mkdir -p "$PREFIX$d"; done
run chown "$PANEL_USER:swg" "$STATE_DIR"; run chmod 750 "$STATE_DIR"
run chown "$PANEL_USER:swg" "$STATS_DIR"; run chmod 2775 "$STATS_DIR"   # panel writes node snapshots here for the dashboard
[ "$STORE_CONFIGS" = true ] && { mkdir -p "$PREFIX$STATE_DIR/configs"; run chown "$PANEL_USER:swg" "$STATE_DIR/configs"; run chmod 750 "$STATE_DIR/configs"; }

# ───────────────────────── panel files ─────────────────────────
info "Panel application"
for f in swg-panel-server index.html app.css app.js reconcile.js; do
  [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"
done
mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/swg-panel-server" "$PREFIX$PANEL_DIR/"; chmod 755 "$PREFIX$PANEL_DIR/swg-panel-server"
for f in index.html app.css app.js reconcile.js; do mkdir -p "$PREFIX$PANEL_DIR"; cp "$SRC/$f" "$PREFIX$PANEL_DIR/"; done
mkdir -p "$PREFIX$PANEL_DIR/vendor"; cp "$SRC/vendor/qrcode.js" "$PREFIX$PANEL_DIR/vendor/"
ok "installed panel + SPA to $PANEL_DIR"
mkdir -p "$PREFIX$STATE_DIR"; [ -f "$PREFIX$STATE_DIR/users.json" ] || { echo '{}' > "$PREFIX$STATE_DIR/users.json"; run chown "$PANEL_USER:swg" "$STATE_DIR/users.json"; ok "seeded empty users.json"; }

# ───────────────────────── host-as-node (this box is also an entry server) ─────────────────────────
LOCAL_TOKHASH=""
if [ "$HOST_HAS_WG" = yes ]; then
  info "This box as a node: agent + swg-noded (syncs to the local panel over HTTPS)"
  mkdir -p "$PREFIX$AGENT_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; chmod 755 "$PREFIX$AGENT_DIR/swg-agent"
  mkdir -p "$PREFIX$NODED_DIR"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"; chmod 755 "$PREFIX$NODED_DIR/swg-noded"
  mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent"

  # how the local node reaches the local panel
  LOCAL_SCHEME=https; [ "$TLS_MODE" = none ] && LOCAL_SCHEME=http
  LOCAL_VERIFY=false; case "$TLS_MODE" in letsencrypt|cloudflare|manual) LOCAL_VERIFY=true;; esac
  if [ "$SERVE_MODE" = standalone ]; then
    if [ "$LOCAL_VERIFY" = true ]; then LOCAL_PANEL_URL="${LOCAL_SCHEME}://${PANEL_DOMAIN}:${PORT}"
    else LOCAL_PANEL_URL="${LOCAL_SCHEME}://127.0.0.1:${PORT}"; fi
  else LOCAL_PANEL_URL="${LOCAL_SCHEME}://${PANEL_DOMAIN}"; fi

  if [ -f "$PREFIX/etc/swg-agent/config.json" ]; then
    ok "keeping existing /etc/swg-agent/config.json (local node already enrolled)"
  else
    # auto-enroll: mint a token for the local node; its hash goes into nodes.json below
    LOCAL_TOKEN="$(head -c18 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=')"
    LOCAL_TOKHASH="$(python3 -c 'import hashlib,os,base64,sys;t=sys.argv[1].encode();s=os.urandom(16);h=hashlib.pbkdf2_hmac("sha256",t,s,200000);print("pbkdf2_sha256$200000$"+base64.b64encode(s).decode()+"$"+base64.b64encode(h).decode())' "$LOCAL_TOKEN")"
    IFJSON=""; sep=""
    for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
      IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\" }"; sep=$',\n'; done
    writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${HOST_ENDPOINT_IP}",
  "dns": ["1.1.1.1"],
  "panel": {
    "url": "${LOCAL_PANEL_URL}",
    "token": "${LOCAL_TOKEN}",
    "verify": ${LOCAL_VERIFY}
  },
  "node": {
    "interval": 5,
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
  fi
  # swg-noded runs as ROOT (samples kernel wg + runs the agent which writes /etc). ProtectSystem=true keeps /etc writable.
  writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to local panel) — ${HOST_NODE_NAME}
After=network-online.target swg-panel-server.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${NODED_DIR}/swg-noded
Environment=SWG_AGENT_CONFIG=/etc/swg-agent/config.json
Environment=SWG_NODED_STATE=/var/lib/swg-noded
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=true
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
fi

# ───────────────────────── nodes.json + fleet.json ─────────────────────────
info "nodes.json + fleet.json"
if [ "$HOST_HAS_WG" = yes ] && [ -n "$LOCAL_TOKHASH" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{
  "${HOST_NODE_NAME}": { "name": "${HOST_NODE_NAME}", "color": "${PALETTE[0]}", "endpoint_host": "${HOST_ENDPOINT_IP}", "stats_file": "stats-${HOST_NODE_NAME}.json", "token_hash": "${LOCAL_TOKHASH}", "created": $(date +%s 2>/dev/null || echo 0) }
}
EOF
elif [ ! -f "$PREFIX$STATE_DIR/nodes.json" ]; then
  writef "$STATE_DIR/nodes.json" 600 <<EOF
{}
EOF
fi
run chown "$PANEL_USER:swg" "$STATE_DIR/nodes.json" 2>/dev/null || true
writef /etc/swg-panel/fleet.json 640 <<EOF
{
  "roster_path":   "${STATE_DIR}/users.json",
  "nodes_path":    "${STATE_DIR}/nodes.json",
  "stats_dir":     "${STATS_DIR}",
  "store_configs": ${STORE_CONFIGS},
  "config_dir":    "${STATE_DIR}/configs",
  "node_interval": 5
}
EOF
run chown "$PANEL_USER:swg" "$ETC_DIR/fleet.json" 2>/dev/null || true

# ───────────────────────── panel-server service ─────────────────────────
write_panel_unit(){   # bind/TLS/auth depend on SERVE_MODE; called from the serve section
  local bind="127.0.0.1" extra=""
  if [ "$SERVE_MODE" = standalone ]; then
    bind="0.0.0.0"
    extra="Environment=SWG_PANEL_AUTH=${ETC_DIR}/auth"
    [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] && extra="$extra
Environment=SWG_PANEL_TLS_CERT=${CERT_FULLCHAIN}
Environment=SWG_PANEL_TLS_KEY=${CERT_KEY}"
    [ "${PORT}" -lt 1024 ] 2>/dev/null && extra="$extra
AmbientCapabilities=CAP_NET_BIND_SERVICE"
  fi
  writef /etc/systemd/system/swg-panel-server.service 644 <<EOF
[Unit]
Description=swg-panel broker
After=network.target

[Service]
Type=simple
User=${PANEL_USER}
ExecStart=${PANEL_DIR}/swg-panel-server
Environment=SWG_PANEL_FLEET=${ETC_DIR}/fleet.json
Environment=SWG_PANEL_WEB=${PANEL_DIR}
Environment=SWG_PANEL_HOST=${bind}
Environment=SWG_PANEL_PORT=${PORT}
${extra}
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${STATE_DIR} ${STATS_DIR}
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
}

# (no push receiver — nodes connect outbound over HTTPS; enroll them in the Nodes screen)

# ───────────────────────── login + TLS + serve mode ─────────────────────────
mk_auth_file(){   # standalone: pbkdf2 login file;  nginx: apr1 htpasswd
  if [ "$SERVE_MODE" = standalone ]; then
    mkdir -p "$PREFIX$ETC_DIR"
    if $DRYRUN; then echo "    [skip] write ${ETC_DIR}/auth (pbkdf2 login for $BASIC_USER)"
      printf '%s:pbkdf2_sha256$200000$DRYRUN$DRYRUN\n' "$BASIC_USER" > "$PREFIX$ETC_DIR/auth"
    else
      python3 - "$BASIC_USER" "$BASIC_PASS" > "$PREFIX$ETC_DIR/auth" <<'PYAUTH'
import sys, os, hashlib, base64
u, pw = sys.argv[1], sys.argv[2]
salt = os.urandom(16); it = 200000
h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
print("%s:pbkdf2_sha256$%d$%s$%s" % (u, it, base64.b64encode(salt).decode(), base64.b64encode(h).decode()))
PYAUTH
    fi
    chmod 640 "$PREFIX$ETC_DIR/auth" 2>/dev/null || true; run chown root:swg "$ETC_DIR/auth"
    ok "login: $BASIC_USER  (stored hashed in ${ETC_DIR}/auth)"
  else
    HTPATH="/etc/nginx/.htpasswd-swg"
    if $DRYRUN; then echo "    [skip] htpasswd $BASIC_USER -> $HTPATH"
    else mkdir -p "$PREFIX/etc/nginx"; echo "$BASIC_USER:$(openssl passwd -apr1 "$BASIC_PASS")" > "$PREFIX$HTPATH"; fi
  fi
}
cert_perms(){ run chown root:swg "$TLS_DIR/fullchain.pem" "$TLS_DIR/key.pem" 2>/dev/null || true
  chmod 644 "$PREFIX$TLS_DIR/fullchain.pem" 2>/dev/null || true; chmod 640 "$PREFIX$TLS_DIR/key.pem" 2>/dev/null || true; }
san_for(){ case "$1" in *[a-zA-Z]*) echo "DNS:$1";; *) echo "IP:$1";; esac; }
find_acme(){ ACME=""; local a; for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do [ -n "$a" ] && [ -x "$a" ] && { ACME="$a"; return 0; }; done; return 1; }
ensure_acme(){ find_acme && return 0
  info "Installing acme.sh"; run sh -c "curl -fsSL https://get.acme.sh | sh -s email=${ACME_EMAIL:-admin@$PANEL_DOMAIN}"
  find_acme && return 0; $DRYRUN && { ACME=/root/.acme.sh/acme.sh; return 0; }
  die "acme.sh not found after install — install it manually or use TLS_MODE=selfsigned/manual"; }
mk_selfsigned(){ CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  if $DRYRUN; then echo "    [skip] openssl self-signed -> $TLS_DIR (CN=$PANEL_DOMAIN)"; : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"
  else run openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$CERT_KEY" -out "$CERT_FULLCHAIN" -subj "/CN=${PANEL_DOMAIN}" -addext "subjectAltName=$(san_for "$PANEL_DOMAIN")"; fi
  cert_perms; ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; }

# ---- standalone: the panel serves its own TLS; cert lands in $TLS_DIR ----
obtain_cert_standalone(){
  mkdir -p "$PREFIX$TLS_DIR"
  case "$TLS_MODE" in
    none) CERT_FULLCHAIN=""; CERT_KEY=""; return 0;;
    selfsigned) mk_selfsigned;;
    manual)
      [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] || die "manual TLS needs CERT_FULLCHAIN and CERT_KEY"
      $DRYRUN || { cp "$CERT_FULLCHAIN" "$PREFIX$TLS_DIR/fullchain.pem"; cp "$CERT_KEY" "$PREFIX$TLS_DIR/key.pem"; }
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; cert_perms; ok "using provided certificate (copied into $TLS_DIR)";;
    letsencrypt|cloudflare)
      ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs CF_TOKEN"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing via Cloudflare DNS-01 for $PANEL_DOMAIN"
      else args+=(--standalone); info "Issuing via Let's Encrypt HTTP-01 (acme standalone :80) for $PANEL_DOMAIN"; fi
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      if ! run "$ACME" "${args[@]}"; then warn "issuance failed — falling back to a self-signed cert."; mk_selfsigned; return; fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" \
          --reloadcmd "chown root:swg $TLS_DIR/fullchain.pem $TLS_DIR/key.pem; chmod 640 $TLS_DIR/key.pem; systemctl restart swg-panel-server"
      cert_perms; ok "issued + installed certificate via $TLS_MODE (auto-renews)";;
    *) die "TLS_MODE must be selfsigned|letsencrypt|cloudflare|manual|none";;
  esac
}
serve_standalone(){
  obtain_cert_standalone
  write_panel_unit
  if command -v ufw >/dev/null 2>&1; then run ufw allow "${PORT}/tcp" 2>/dev/null || true; fi
  local sch="https"; [ -n "${CERT_FULLCHAIN:-}" ] || sch="http"
  [ "$sch" = http ] && warn "TLS=none — login travels in the clear. Use selfsigned/letsencrypt/cloudflare for real use."
  ok "Standalone: panel serves ${sch}://${PANEL_DOMAIN}:${PORT}/ directly (no nginx)"
}

# ---- nginx: panel on loopback, nginx terminates TLS + auth ----
write_vhost(){   # write_vhost bootstrap|tls
  if [ "$1" = tls ]; then
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { auth_basic off; root ${ACME_WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name ${PANEL_DOMAIN};
    ssl_certificate ${CERT_FULLCHAIN};
    ssl_certificate_key ${CERT_KEY};
    auth_basic "swg-panel";
    auth_basic_user_file ${HTPATH};

    location /wgstats/ { alias ${STATS_DIR}/; add_header Cache-Control "no-store"; }
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
}
EOF
  else
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { auth_basic off; root ${ACME_WEBROOT}; }

    auth_basic "swg-panel";
    auth_basic_user_file ${HTPATH};
    location /wgstats/ { alias ${STATS_DIR}/; add_header Cache-Control "no-store"; }
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
    }
}
EOF
  fi
  if [ -d /etc/nginx/sites-enabled ]; then run ln -sf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/sites-enabled/swg-panel.conf
  elif [ -d /etc/nginx/conf.d ]; then cp "$PREFIX/etc/nginx/sites-available/swg-panel.conf" "$PREFIX/etc/nginx/conf.d/swg-panel.conf"; fi
}
setup_tls(){   # nginx-mode cert into $TLS_DIR
  case "$TLS_MODE" in
    selfsigned) mk_selfsigned;;
    none) CERT_FULLCHAIN=""; CERT_KEY=""; return 0;;
    manual) [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] || die "manual TLS needs CERT_FULLCHAIN and CERT_KEY"
            $DRYRUN || { [ -f "$CERT_FULLCHAIN" ] || warn "cert not found yet: $CERT_FULLCHAIN"; }; ok "using provided certificate: $CERT_FULLCHAIN";;
    letsencrypt|cloudflare)
      mkdir -p "$PREFIX$TLS_DIR"; ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs CF_TOKEN"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
      else args+=(--webroot "$ACME_WEBROOT"); fi
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      if ! run "$ACME" "${args[@]}"; then warn "issuance failed — staying on :80."; CERT_FULLCHAIN=""; CERT_KEY=""; return 0; fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" --reloadcmd "systemctl reload nginx"
      cert_perms; ok "issued + installed certificate via $TLS_MODE";;
    *) die "TLS_MODE must be selfsigned|letsencrypt|cloudflare|manual|none";;
  esac
}
serve_nginx(){
  mkdir -p "$PREFIX$ACME_WEBROOT"
  write_panel_unit
  write_vhost bootstrap
  run nginx -t && run systemctl reload nginx || warn "nginx -t failed (is nginx installed?) — fix, then: systemctl reload nginx"
  setup_tls
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then
    write_vhost tls
    run nginx -t && run systemctl reload nginx || warn "nginx -t failed after enabling TLS — check $CERT_FULLCHAIN"
    ok "nginx: TLS enabled for https://${PANEL_DOMAIN}/"
  else warn "nginx: serving on :80 without TLS — front with TLS before exposing."; fi
}

info "Login + TLS ($SERVE_MODE)"
mk_auth_file
case "$SERVE_MODE" in standalone) serve_standalone;; nginx) serve_nginx;; esac


# ───────────────────────── enable ─────────────────────────
info "Enable services"
run systemctl daemon-reload
[ "$HOST_HAS_WG" = yes ] && run systemctl enable --now swg-noded
run systemctl enable --now swg-panel-server
[ "$SERVE_MODE" = nginx ] && { run nginx -t && run systemctl reload nginx || warn "nginx -t failed; fix the vhost then: systemctl reload nginx"; }

# ───────────────────────── handoff ─────────────────────────
echo; ok "Host install complete."
if [ "$SERVE_MODE" = standalone ]; then
  SCH=https; [ -n "${CERT_FULLCHAIN:-}" ] || SCH=http
  echo "  UI:    ${SCH}://${PANEL_DOMAIN}:${PORT}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
  command -v ufw >/dev/null 2>&1 || echo "         open TCP ${PORT} in your firewall if it isn't already"
  [ "$TLS_MODE" = selfsigned ] && echo "         self-signed cert — the browser warns once, that's expected"
elif [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then echo "  UI:    https://${PANEL_DOMAIN}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
else echo "  UI:    http://${PANEL_DOMAIN}/  [no TLS]   (login: ${BASIC_USER} / ${BASIC_PASS})"; fi
echo "  Local: curl -s 127.0.0.1:${PORT}/api/fleet"
echo
echo "Add entry servers from the UI: Nodes → Add node issues a one-time token and the"
echo "exact install-node.sh command to run on each server (outbound HTTPS only — no inbound)."
[ "$HOST_HAS_WG" = yes ] && echo "This box is enrolled as node '${HOST_NODE_NAME}'; it appears in Nodes once swg-noded syncs."
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun"; }
