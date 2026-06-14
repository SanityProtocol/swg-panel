#!/usr/bin/env bash
# install-host.sh — set up the swg-panel host (server + UI + collector + receiver).
#
# Two roles, chosen in Step 1 (or via ROLE): master or host.
#   master  panel + this box also runs wg/awg interfaces (an entry server)
#   host    panel only; wg/awg nodes are deployed separately
#
# Fill the CONFIG block to run unattended, or leave blanks to be prompted.
# Run as root. Use --dry-run to render every file under ./dryrun and execute nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
METHOD="${METHOD:-baremetal}"          # baremetal (systemd). For Docker, use docker-compose instead.
ROLE="${ROLE:-}"                       # master (panel + this box is an entry server) | host (panel only)
HOST_NODE_NAME="${HOST_NODE_NAME:-}"   # node name for THIS box (master only)
HOST_ENDPOINT_IP="${HOST_ENDPOINT_IP:-}" # public IP clients dial for this box's wg (master only)
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = manage all detected; master only)

PANEL_DOMAIN="${PANEL_DOMAIN:-}"       # panel URL: IP, host, or host/subpath (e.g. vpn.example.com/swg). Blank = this host's IP.
STORE_CONFIGS="${STORE_CONFIGS:-false}"

SERVE_MODE="${SERVE_MODE:-}"           # internal (self-contained) | nginx | caddy | skip  (blank = ask)
# TLS — how to obtain the certificate:
TLS_MODE="${TLS_MODE:-}"               # cloudflare | letsencrypt | selfsigned | skip  (blank = ask)
ACME_EMAIL="${ACME_EMAIL:-}"           # account email for letsencrypt/cloudflare
CF_TOKEN="${CF_TOKEN:-}"               # cloudflare: API token with Zone:DNS:Edit
CF_ACCOUNT_ID="${CF_ACCOUNT_ID:-}"     # cloudflare: optional account id
CERT_FULLCHAIN="${CERT_FULLCHAIN:-}"   # skip-with-own-cert: path to fullchain.pem
CERT_KEY="${CERT_KEY:-}"               # skip-with-own-cert: path to private key.pem
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
PANEL_BASE="${PANEL_BASE:-}"           # derived from PANEL_DOMAIN's path (e.g. /swg); blank = served at root
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

detect_public_ip(){ # best public IPv4: default-route source, then first hostname -I
  local ip; ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1 || true)"
  [ -z "$ip" ] && ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
  printf '%s' "$ip"; }
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }

parse_panel_url(){ # parse_panel_url <input> -> sets PANEL_HOST_NOPORT, PANEL_BASE, URL_PORT
  local u="$1" hostport rest
  u="${u#http://}"; u="${u#https://}"; u="${u%/}"
  hostport="${u%%/*}"                       # host[:port]
  rest="${u#"$hostport"}"                    # remaining /path (may be empty)
  PANEL_BASE="$rest"; [ "$PANEL_BASE" = "/" ] && PANEL_BASE=""
  PANEL_BASE="${PANEL_BASE%/}"               # no trailing slash
  case "$hostport" in
    *:*) PANEL_HOST_NOPORT="${hostport%%:*}"; URL_PORT="${hostport##*:}";;
    *)   PANEL_HOST_NOPORT="$hostport"; URL_PORT="";;
  esac
}

# ───────────────────────── wg/awg detection ─────────────────────────
declare -A IF_CMD IF_CONF
detect_wg(){ # scan everything under /etc/amnezia (any subdir) for awg, and /etc/wireguard for wg
  IF_CMD=(); IF_CONF=(); local f n
  if [ -d /etc/amnezia ]; then
    while IFS= read -r f; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"
    done < <(find /etc/amnezia -maxdepth 3 -type f -name '*.conf' 2>/dev/null)
  fi
  for f in /etc/wireguard/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg; IF_CONF[$n]="$f"; done
}
choose_ifaces(){ # populate SELECTED[] — all detected interfaces are managed; 'new' creates more
  detect_wg
  if [ -n "$MANAGE_IFACES" ]; then
    IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    info "Checking for wg / awg on this host…"
    if [ "${#IF_CMD[@]}" -eq 0 ]; then
      warn "No wg / awg interfaces found in /etc/wireguard or /etc/amnezia."
      local doit; ask_yn "Create one now? (installs WireGuard / AmneziaWG only if missing)" y doit
      [ "$doit" = yes ] && create_iface
      detect_wg
      [ "${#IF_CMD[@]}" -eq 0 ] && die "No interface. Create one, then re-run (or set MANAGE_IFACES)."
    fi
    local names=() pick
    while :; do
      detect_wg; names=("${!IF_CMD[@]}")
      echo; printf "  Available interfaces:"; for n in "${names[@]}"; do printf ' %s (%s)' "$n" "${IF_CMD[$n]}"; done; echo
      if ! read -rp "  Press Enter to proceed with the setup or enter \"new\" to create an additional interface: " pick </dev/tty 2>/dev/null; then
        warn "no interactive input — managing all detected interfaces"; break
      fi
      pick="${pick//[[:space:]]/}"
      [ "$pick" = new ] && { create_iface; continue; }
      [ -z "$pick" ] && break
      warn "enter nothing to proceed, or \"new\" to add another interface"
    done
    SELECTED=("${names[@]}")          # every detected interface ends up in the web panel
  fi
  detect_wg
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }; done
  ok "Managing: ${SELECTED[*]}"
}
ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools + kernel module if missing (idempotent)
  local cmd="$1"
  if [ "$cmd" = wg ]; then
    have wg && return 0
    run apt-get update -qq; run apt-get install -y wireguard
  else
    have awg && return 0
    run apt-get update -qq; run apt-get install -y software-properties-common
    run add-apt-repository -y ppa:amnezia/ppa; run apt-get update -qq; run apt-get install -y amneziawg
  fi
}
awg_obfuscation(){ # emit AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, and a conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))   # v2 init/response junk sizes
  b1=$(( 5          + (RANDOM*RANDOM) % 900000000 ))       # four disjoint bands keep H1–H4
  b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))       # distinct and non-overlapping, all > 4
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 ))
  b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  # Conservative QUIC-Initial mimicry on I1 only (no <c> counters, no <t> — keeps amneziawg-go/Android working).
  # 0xc3 = long-header Initial first byte; 0x00000001 = QUIC v1; then random payload.
  printf 'I1 = <b 0xc300000001><r 1200>\n'
}
server_addr(){ # server_addr <cidr> -> "<first-host>/<prefix>"
  have python3 || die "python3 is required to compute the tunnel address (it's also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
create_iface(){ # prompt, gen server key, write conf (AWG v2 + QUIC I1, or plain WG), NAT it to the WAN, bring up, register
  local _proto proto name port subnet addr conf cmd priv dir wan up down
  ask "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto; proto="${_proto:-a}"
  case "$proto" in w|wg|wireguard) proto=wg; cmd=wg;  dir=/etc/wireguard;;
                                *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  ask "Interface name" "$([ "$cmd" = awg ] && echo awg0 || echo wg0)" name
  ask "Listen port"    "51820"        port
  ask "Tunnel subnet (CIDR; server takes the first host)" "10.8.0.0/24" subnet
  ask "WAN egress interface (clients are NAT'd out using this)" "$(detect_wan || echo eth0)" wan
  addr="$(server_addr "$subnet")"; conf="$dir/$name.conf"
  ensure_wg_tools "$cmd"
  # gateway plumbing: forward + masquerade the tunnel subnet out the WAN (bound to iface lifecycle)
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
  run sysctl -q -w net.ipv4.ip_forward=1
  if $DRYRUN; then priv="<generated-on-real-run>"; else priv="$("$cmd" genkey)"; fi
  { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\n' "$priv" "$addr" "$port"
    printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
    if [ "$cmd" = awg ]; then awg_obfuscation; fi; } | writef "$conf" 600
  if [ "$cmd" = awg ]; then run awg-quick up "$name"; run systemctl enable "awg-quick@$name"
  else                     run wg-quick  up "$name"; run systemctl enable "wg-quick@$name"; fi
  IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; LAST_IFACE="$name"
  ok "created $proto interface '$name' on :$port (server $addr, NAT out $wan)"
}

# ───────────────────────── prompts ─────────────────────────
[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

# ═══════════════ I. PANEL SETUP ═══════════════
echo; info "PANEL SETUP"

# Step 1 — server role
ROLE_SEL=""
case "$ROLE" in master|host+node) ROLE_SEL=master;; host) ROLE_SEL=host;; node) die "for a node-only box run install-node.sh, not this script";; esac
echo
echo "Step 1. Server role:"
echo
echo "  master (default)"
echo "      Masternode — this server will host the panel and run WG/AWG interfaces"
echo "  host"
echo "      This server will host only the panel. WG/AWG nodes will be deployed separately"
echo
ask "Select role" "master" ROLE_SEL
case "$ROLE_SEL" in master) ROLE="host+node";; host) ROLE="host";; *) die "role must be 'master' or 'host'";; esac
HOST_HAS_WG=no; [ "$ROLE" = "host+node" ] && HOST_HAS_WG=yes

# Step 2 — panel URL (may include a subpath, e.g. vpn.example.com/swg)
echo
echo "Step 2. Panel URL"
echo "      Where the panel is reached — an IP, a host, or a host with a subpath to"
echo "      live under an existing site (e.g. vpn.example.com/swg)."
DEF_URL="$(detect_public_ip)"; [ -z "$DEF_URL" ] && DEF_URL=localhost
ask "Enter panel URL" "$DEF_URL" PANEL_DOMAIN
parse_panel_url "$PANEL_DOMAIN"
PANEL_DOMAIN="$PANEL_HOST_NOPORT"
[ -z "$PANEL_DOMAIN" ] && PANEL_DOMAIN=localhost
[ -n "$PANEL_BASE" ] && ok "panel will be served under subpath ${PANEL_BASE}/"

# Step 3 — TLS certificate
echo
echo "Step 3. TLS certificate"
echo
echo "  cloudflare (default)"
echo "      Cloudflare DNS-01 — requires a Zone:DNS:Edit API token and account email"
echo "  letsencrypt"
echo "      Issue a Let's Encrypt certificate using acme.sh"
echo "  selfsigned"
echo "      OK for testing / playing around"
echo "  skip"
echo "      If you are planning to use your own certificate (or terminate TLS elsewhere)"
echo
[ -z "$TLS_MODE" ] && [ -n "$CERT_FULLCHAIN" ] && [ -n "$CERT_KEY" ] && TLS_MODE=skip
ask "Select TLS certificate" "cloudflare" TLS_MODE
case "$TLS_MODE" in
  cloudflare)  ask "Cloudflare API token (Zone:DNS:Edit)" "" CF_TOKEN; ask "ACME account email" "" ACME_EMAIL;;
  letsencrypt) ask "ACME account email" "" ACME_EMAIL;;
  selfsigned) ;;
  skip|manual|none) TLS_MODE=skip;;
  *) die "TLS must be cloudflare|letsencrypt|selfsigned|skip";;
esac
if [ "$TLS_MODE" = letsencrypt ] || [ "$TLS_MODE" = cloudflare ]; then
  case "$PANEL_DOMAIN" in *[a-zA-Z]*) : ;; *) die "TLS=$TLS_MODE needs a real domain in the panel URL (not an IP) — use selfsigned for an IP";; esac
  case "$PANEL_DOMAIN" in *.*) : ;; *) die "panel URL must be a FQDN for $TLS_MODE";; esac
fi

# Step 4 — web serve mode
echo
echo "Step 4. Web serve mode:"
echo
echo "  internal (default)"
echo "      Self-contained, no separate web-server is required"
echo "  nginx"
echo "      Web content will be served via an Nginx reverse proxy"
echo "  caddy"
echo "      Web content will be served via a Caddy reverse proxy"
echo "  skip"
echo "      If you are planning to configure the web server manually"
echo
case "$SERVE_MODE" in standalone) SERVE_MODE=internal;; esac
ask "Select mode" "internal" SERVE_MODE
case "$SERVE_MODE" in internal|nginx|caddy|skip) ;; *) die "mode must be internal|nginx|caddy|skip";; esac

# port: internal serves the public port itself; proxy/manual modes keep the panel on a loopback port
if [ "$SERVE_MODE" = internal ]; then
  [ -z "$PORT" ] && PORT="${URL_PORT:-443}"
  ask "Public HTTPS port for the panel" "$PORT" PORT
else
  [ -z "$PORT" ] && PORT="${URL_PORT:-8088}"
fi

# Admin login — username suggested as admin + 3 random digits; password auto-generated (printed at the end).
[ -z "$BASIC_PASS" ] && BASIC_PASS="$(head -c12 /dev/urandom | base64 | tr -d '/+=' | head -c16)"
if [ "${BASIC_USER}" = admin ]; then BASIC_USER="admin$(( RANDOM % 900 + 100 ))"; fi
ask "Panel admin username" "$BASIC_USER" BASIC_USER

# ═══════════════ II. NODE SETUP (master only) ═══════════════
declare -a SELECTED
if [ "$HOST_HAS_WG" = yes ]; then
  echo; info "NODE SETUP"
  echo
  echo "Step 1. Node name for THIS box"
  ask "Node name for THIS box" "$(hostname -s 2>/dev/null || hostname)" HOST_NODE_NAME
  echo
  echo "Step 2. Endpoint IP clients dial for THIS box"
  ask "Endpoint IP clients dial for THIS box" "$(detect_public_ip)" HOST_ENDPOINT_IP
  echo
  echo "Step 3. WireGuard / AmneziaWG setup"
  choose_ifaces
fi

echo; info "Plan: method=$METHOD role=$ROLE serve=$SERVE_MODE tls=$TLS_MODE base=${PANEL_BASE:-/} store_configs=$STORE_CONFIGS"

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

  # the local node always reaches the local panel on loopback (works for every serve mode);
  # scheme is https only when the panel terminates TLS itself (internal mode with a cert).
  LOCAL_SCHEME=http
  [ "$SERVE_MODE" = internal ] && [ "$TLS_MODE" != skip ] && LOCAL_SCHEME=https
  LOCAL_PANEL_URL="${LOCAL_SCHEME}://127.0.0.1:${PORT}${PANEL_BASE}"

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
    "verify": false
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
write_panel_unit(){   # bind/TLS/base depend on SERVE_MODE; called from the serve section
  local bind="127.0.0.1" extra=""
  extra="Environment=SWG_PANEL_AUTH=${ETC_DIR}/auth"            # panel does its own login in every serve mode
  [ -n "$PANEL_BASE" ] && extra="$extra
Environment=SWG_PANEL_BASE=${PANEL_BASE}"
  if [ "$SERVE_MODE" = internal ]; then
    bind="0.0.0.0"                                              # internal mode faces the network directly
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
ReadWritePaths=${ETC_DIR} ${STATE_DIR} ${STATS_DIR}
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
}

# (no push receiver — nodes connect outbound over HTTPS; enroll them in the Nodes screen)

# ───────────────────────── login + TLS + serve mode ─────────────────────────
mk_auth_file(){   # panel login file (pbkdf2) — used by every serve mode so the Account tab works
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
}
cert_perms(){ run chown root:swg "$TLS_DIR/fullchain.pem" "$TLS_DIR/key.pem" 2>/dev/null || true
  chmod 644 "$PREFIX$TLS_DIR/fullchain.pem" 2>/dev/null || true; chmod 640 "$PREFIX$TLS_DIR/key.pem" 2>/dev/null || true; }
san_for(){ case "$1" in *[a-zA-Z]*) echo "DNS:$1";; *) echo "IP:$1";; esac; }
find_acme(){ ACME=""; local a; for a in /root/.acme.sh/acme.sh "${HOME:-/root}/.acme.sh/acme.sh" "$(command -v acme.sh 2>/dev/null || true)"; do [ -n "$a" ] && [ -x "$a" ] && { ACME="$a"; return 0; }; done; return 1; }
ensure_acme(){ find_acme && return 0
  info "Installing acme.sh"; run sh -c "curl -fsSL https://get.acme.sh | sh -s email=${ACME_EMAIL:-admin@$PANEL_DOMAIN}"
  find_acme && return 0; $DRYRUN && { ACME=/root/.acme.sh/acme.sh; return 0; }
  die "acme.sh not found after install — install it manually or use TLS=selfsigned/skip"; }
mk_selfsigned(){ CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; mkdir -p "$PREFIX$TLS_DIR"
  if $DRYRUN; then echo "    [skip] openssl self-signed -> $TLS_DIR (CN=$PANEL_DOMAIN)"; : > "$PREFIX$CERT_FULLCHAIN"; : > "$PREFIX$CERT_KEY"
  else run openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$CERT_KEY" -out "$CERT_FULLCHAIN" -subj "/CN=${PANEL_DOMAIN}" -addext "subjectAltName=$(san_for "$PANEL_DOMAIN")"; fi
  cert_perms; ok "self-signed certificate for ${PANEL_DOMAIN} (10y)"; }
use_provided_certs(){   # skip-with-own-cert: copy caller-supplied cert into $TLS_DIR; 0 if used, 1 if none
  [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ] || return 1
  mkdir -p "$PREFIX$TLS_DIR"
  $DRYRUN || { cp "$CERT_FULLCHAIN" "$PREFIX$TLS_DIR/fullchain.pem"; cp "$CERT_KEY" "$PREFIX$TLS_DIR/key.pem"; }
  CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"; cert_perms
  ok "using provided certificate (copied into $TLS_DIR)"; return 0; }

# ---- internal: the panel serves its own TLS; cert lands in $TLS_DIR ----
obtain_cert_internal(){
  mkdir -p "$PREFIX$TLS_DIR"
  case "$TLS_MODE" in
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — panel will serve plain HTTP"; }; return 0;;
    selfsigned) mk_selfsigned;;
    letsencrypt|cloudflare)
      ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs CF_TOKEN"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
        info "Issuing via Cloudflare DNS-01 for $PANEL_DOMAIN"
      else args+=(--standalone); info "Issuing via Let's Encrypt HTTP-01 (acme standalone :80) for $PANEL_DOMAIN"; fi
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      local rc=0; run "$ACME" "${args[@]}" || rc=$?
      # acme.sh exit 2 = RENEW_SKIP (a valid cert already exists, not due for renewal) — that's fine.
      if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
        if $DRYRUN || $ACME --info -d "$PANEL_DOMAIN" >/dev/null 2>&1; then
          warn "acme.sh returned $rc but a cert for $PANEL_DOMAIN exists — installing it."
        else
          warn "issuance failed (acme.sh exit $rc) — falling back to a self-signed cert."; mk_selfsigned; return
        fi
      fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" \
          --reloadcmd "chown root:swg $TLS_DIR/fullchain.pem $TLS_DIR/key.pem; chmod 640 $TLS_DIR/key.pem; systemctl restart swg-panel-server"
      cert_perms; ok "issued + installed certificate via $TLS_MODE (auto-renews)";;
    *) die "TLS must be cloudflare|letsencrypt|selfsigned|skip";;
  esac
}
serve_internal(){
  # acme's --install-cert reloadcmd runs `systemctl restart swg-panel-server` immediately,
  # so the unit must exist (and be loaded) BEFORE issuance — write+enable a TLS-less
  # placeholder first, then rewrite with the real cert paths and restart for real.
  write_panel_unit
  run systemctl daemon-reload
  run systemctl enable --now swg-panel-server
  obtain_cert_internal
  write_panel_unit
  run systemctl daemon-reload
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then run systemctl restart swg-panel-server; fi
  if command -v ufw >/dev/null 2>&1; then run ufw allow "${PORT}/tcp" 2>/dev/null || true; fi
  local sch="https"; [ -n "${CERT_FULLCHAIN:-}" ] || sch="http"
  [ "$sch" = http ] && warn "TLS skipped — login travels in the clear. Use selfsigned/letsencrypt/cloudflare for real use."
  ok "Internal: panel serves ${sch}://${PANEL_DOMAIN}:${PORT}${PANEL_BASE}/ directly (no extra web server)"
}

# ---- reverse-proxy (nginx / caddy): panel on loopback, proxy terminates TLS ----
setup_tls_proxy(){   # issue/locate a cert into $TLS_DIR for a reverse proxy to use
  case "$TLS_MODE" in
    selfsigned) mk_selfsigned;;
    skip) use_provided_certs || { CERT_FULLCHAIN=""; CERT_KEY=""; ok "TLS skipped — proxy will serve plain HTTP (or add your own cert)"; }; return 0;;
    letsencrypt|cloudflare)
      mkdir -p "$PREFIX$TLS_DIR"; ensure_acme
      local args=(--issue -d "$PANEL_DOMAIN" --server letsencrypt --keylength ec-256)
      if [ "$TLS_MODE" = cloudflare ]; then [ -n "$CF_TOKEN" ] || die "cloudflare needs CF_TOKEN"
        export CF_Token="$CF_TOKEN"; [ -n "$CF_ACCOUNT_ID" ] && export CF_Account_ID="$CF_ACCOUNT_ID"; args+=(--dns dns_cf)
      elif [ "$SERVE_MODE" = nginx ]; then args+=(--webroot "$ACME_WEBROOT")    # nginx already serves :80 for the challenge
      else args+=(--standalone); fi                                            # caddy not up yet → acme can hold :80
      [ -n "$ACME_EMAIL" ] && { run "$ACME" --register-account -m "$ACME_EMAIL" --server letsencrypt || true; }
      local reload="systemctl reload nginx"; [ "$SERVE_MODE" = caddy ] && reload="systemctl reload caddy"
      if ! run "$ACME" "${args[@]}"; then warn "issuance failed — proxy will serve plain HTTP."; CERT_FULLCHAIN=""; CERT_KEY=""; return 0; fi
      CERT_FULLCHAIN="$TLS_DIR/fullchain.pem"; CERT_KEY="$TLS_DIR/key.pem"
      run "$ACME" --install-cert -d "$PANEL_DOMAIN" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULLCHAIN" --reloadcmd "$reload"
      cert_perms; ok "issued + installed certificate via $TLS_MODE";;
    *) die "TLS must be cloudflare|letsencrypt|selfsigned|skip";;
  esac
}
proxy_loc(){ [ -n "$PANEL_BASE" ] && printf '%s/' "$PANEL_BASE" || printf '/'; }   # nginx location path

write_vhost(){   # write_vhost bootstrap|tls    (nginx)
  local loc; loc="$(proxy_loc)"
  if [ "$1" = tls ]; then
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name ${PANEL_DOMAIN};
    ssl_certificate ${CERT_FULLCHAIN};
    ssl_certificate_key ${CERT_KEY};

    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  else
    writef /etc/nginx/sites-available/swg-panel.conf 644 <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location ^~ /.well-known/acme-challenge/ { root ${ACME_WEBROOT}; }
    location ${loc} {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  fi
  if [ -d /etc/nginx/sites-enabled ]; then run ln -sf /etc/nginx/sites-available/swg-panel.conf /etc/nginx/sites-enabled/swg-panel.conf
  elif [ -d /etc/nginx/conf.d ]; then cp "$PREFIX/etc/nginx/sites-available/swg-panel.conf" "$PREFIX/etc/nginx/conf.d/swg-panel.conf"; fi
}
serve_nginx(){
  mkdir -p "$PREFIX$ACME_WEBROOT"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  write_vhost bootstrap
  run nginx -t && run systemctl reload nginx || warn "nginx -t failed (is nginx installed?) — fix, then: systemctl reload nginx"
  setup_tls_proxy
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then
    write_vhost tls
    run nginx -t && run systemctl reload nginx || warn "nginx -t failed after enabling TLS — check $CERT_FULLCHAIN"
    ok "nginx: TLS enabled for https://${PANEL_DOMAIN}${PANEL_BASE}/"
  else warn "nginx: serving on :80 without TLS — front with TLS before exposing."; fi
}

ensure_caddy_import(){   # make the main Caddyfile import our drop-in
  local main=/etc/caddy/Caddyfile
  if $DRYRUN; then echo "    [skip] ensure 'import conf.d/*.caddy' in $main"; return 0; fi
  mkdir -p /etc/caddy/conf.d; touch "$main"
  grep -qF 'conf.d/*.caddy' "$main" 2>/dev/null || printf '\nimport conf.d/*.caddy\n' >> "$main"
}
write_caddy_site(){
  local site="$PANEL_DOMAIN" tls="" handle="handle"
  [ -n "$PANEL_BASE" ] && handle="handle ${PANEL_BASE}/*"
  if [ -n "${CERT_FULLCHAIN:-}" ] && [ -n "${CERT_KEY:-}" ]; then tls="    tls ${CERT_FULLCHAIN} ${CERT_KEY}"
  elif [ "$TLS_MODE" = selfsigned ]; then tls="    tls internal"
  elif [ "$TLS_MODE" = skip ]; then site="http://${PANEL_DOMAIN}"; fi
  writef /etc/caddy/conf.d/swg-panel.caddy 644 <<EOF
${site} {
${tls}
    ${handle} {
        reverse_proxy 127.0.0.1:${PORT}
    }
}
EOF
  ensure_caddy_import
}
serve_caddy(){
  have caddy || warn "caddy not found — install it (https://caddyserver.com), then re-run or 'systemctl reload caddy'"
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  setup_tls_proxy            # caddy isn't up yet, so acme standalone (:80) is free for letsencrypt
  write_caddy_site
  run systemctl reload caddy 2>/dev/null || run systemctl restart caddy 2>/dev/null || warn "couldn't (re)load caddy — start it after checking /etc/caddy/conf.d/swg-panel.caddy"
  local sch="https"; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && sch="http"
  ok "caddy: serving ${sch}://${PANEL_DOMAIN}${PANEL_BASE}/"
}

serve_skip(){
  write_panel_unit
  run systemctl daemon-reload; run systemctl enable --now swg-panel-server
  ok "Panel running on 127.0.0.1:${PORT}${PANEL_BASE} — configure your web server to proxy to it."
  echo "    nginx example:"
  echo "      location $(proxy_loc) { proxy_pass http://127.0.0.1:${PORT}; proxy_set_header Host \$host; }"
}

info "Login + TLS ($SERVE_MODE)"
mk_auth_file
case "$SERVE_MODE" in
  internal) serve_internal;;
  nginx)    serve_nginx;;
  caddy)    serve_caddy;;
  skip)     serve_skip;;
esac

# ───────────────────────── enable ─────────────────────────
info "Enable services"
run systemctl daemon-reload
[ "$HOST_HAS_WG" = yes ] && run systemctl enable --now swg-noded
run systemctl enable --now swg-panel-server
[ "$SERVE_MODE" = nginx ] && { run nginx -t && run systemctl reload nginx || warn "nginx -t failed; fix the vhost then: systemctl reload nginx"; }

# ───────────────────────── handoff ─────────────────────────
echo; ok "Host install complete."
case "$SERVE_MODE" in
  internal)
    SCH=https; [ -n "${CERT_FULLCHAIN:-}" ] || SCH=http
    PORTSUF=""; [ "$PORT" != 443 ] && PORTSUF=":${PORT}"
    echo "  UI:    ${SCH}://${PANEL_DOMAIN}${PORTSUF}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    command -v ufw >/dev/null 2>&1 || echo "         open TCP ${PORT} in your firewall if it isn't already"
    [ "$TLS_MODE" = selfsigned ] && echo "         self-signed cert — the browser warns once, that's expected"
    ;;
  nginx|caddy)
    SCH=https; { [ "$TLS_MODE" = skip ] && [ -z "${CERT_FULLCHAIN:-}" ]; } && SCH=http
    echo "  UI:    ${SCH}://${PANEL_DOMAIN}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    ;;
  skip)
    echo "  Panel: http://127.0.0.1:${PORT}${PANEL_BASE}/   (login: ${BASIC_USER} / ${BASIC_PASS})"
    echo "         point your web server at it (proxy ${PANEL_BASE:-/} → 127.0.0.1:${PORT})"
    ;;
esac
echo "  Local: curl -s 127.0.0.1:${PORT}${PANEL_BASE}/api/fleet"
echo
echo "Add entry servers from the UI: Nodes → Add node issues a one-time token and the"
echo "exact install-node.sh command to run on each server (outbound HTTPS only — no inbound)."
[ "$HOST_HAS_WG" = yes ] && echo "This box is enrolled as node '${HOST_NODE_NAME}'; it appears in Nodes once swg-noded syncs."
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun"; }
