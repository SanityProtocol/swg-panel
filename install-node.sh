#!/usr/bin/env bash
# install-node.sh — set up a swg-panel NODE (entry server).
#
# Installs the agent + the swg-noded daemon and points it at your panel. The node
# makes ONLY outbound HTTPS to the panel: every few seconds it posts its snapshot
# and receives its desired peer set, then reconciles locally. No inbound access,
# no SSH keys, no rsync, no queue.
#
# First add the node in the panel's "Nodes" screen — it hands you a one-time token
# and the exact command to run here, e.g.:
#     sudo PANEL_URL="https://panel.example.net:8443" NODE_TOKEN="…" ./install-node.sh
#
# Fill CONFIG to run unattended, or be prompted. Run as root. --dry-run renders
# files under ./dryrun and executes nothing.
set -euo pipefail

# ───────────────────────── CONFIG (blank = ask) ─────────────────────────
PANEL_URL="${PANEL_URL:-}"             # https://host:port of the panel
NODE_TOKEN="${NODE_TOKEN:-}"           # one-time enrollment token from the Nodes screen
ENDPOINT_IP="${ENDPOINT_IP:-}"         # public IP/host clients dial for THIS node's wg
MANAGE_IFACES="${MANAGE_IFACES:-}"     # e.g. "awg0"  (blank = pick from detected)
DNS="${DNS:-1.1.1.1}"
TLS_VERIFY="${TLS_VERIFY:-}"           # yes = verify panel's cert (real CA); no = self-signed
TLS_FINGERPRINT="${TLS_FINGERPRINT:-}" # optional: pin panel cert sha256 (hex) instead of verify
INTERVAL="${INTERVAL:-5}"              # sync period, seconds
AGENT_DIR="${AGENT_DIR:-/opt/swg-agent}"
NODED_DIR="${NODED_DIR:-/opt/swg-noded}"
# ────────────────────────────────────────────────────────────────────────

DRYRUN=false; [ "${1:-}" = "--dry-run" ] && DRYRUN=true
PREFIX=""; $DRYRUN && PREFIX="$(pwd)/dryrun"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c(){ printf '\033[%sm' "$1"; }
info(){ echo "$(c '0;36')▸$(c 0) $*"; }
ok(){   echo "$(c '0;32')✓$(c 0) $*"; }
warn(){ echo "$(c '0;33')!$(c 0) $*" >&2; }
die(){  echo "$(c '0;31')✗ $*$(c 0)" >&2; exit 1; }
have(){ command -v "$1" >/dev/null 2>&1; }
run(){ if $DRYRUN; then echo "    [skip] $*"; else "$@"; fi; }
writef(){ local p="$1" m="${2:-644}" full="$PREFIX$1"; mkdir -p "$(dirname "$full")"; cat > "$full"; chmod "$m" "$full" 2>/dev/null || true; ok "wrote $p ($m)"; }
ask(){ local v p="$1" d="${2:-}"; if [ -n "${!3:-}" ]; then return; fi; read -rp "$p${d:+ [$d]}: " v </dev/tty || true; printf -v "$3" '%s' "${v:-$d}"; }
ask_yn(){ local v p="$1" d="${2:-y}"; if [ -n "${!3:-}" ]; then return; fi; read -rp "$p ($([ "$d" = y ] && echo 'Y/n' || echo 'y/N')): " v </dev/tty || true; v="${v:-$d}"; case "$v" in [Yy]*) printf -v "$3" yes;; *) printf -v "$3" no;; esac; }

declare -A IF_CMD IF_CONF; declare -a SELECTED
detect_wg(){ IF_CMD=(); IF_CONF=(); local f n
  for f in /etc/amnezia/amneziawg/*.conf; do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=awg; IF_CONF[$n]="$f"; done
  for f in /etc/wireguard/*.conf;        do [ -e "$f" ] || continue; n="$(basename "$f" .conf)"; IF_CMD[$n]=wg;  IF_CONF[$n]="$f"; done
}
install_wg(){ local kind; read -rp "  Install (a)mneziawg or (w)ireguard? [a]: " kind </dev/tty || true; kind="${kind:-a}"
  if [ "$kind" = w ]; then run apt-get update -qq; run apt-get install -y wireguard
  else run apt-get update -qq; run apt-get install -y software-properties-common; run add-apt-repository -y ppa:amnezia/ppa; run apt-get update -qq; run apt-get install -y amneziawg; fi; }
choose_ifaces(){
  detect_wg
  if [ "${#IF_CMD[@]}" -eq 0 ]; then
    warn "No wg/awg interfaces found."; local d; ask_yn "Install now?" y _ans; d="$_ans"
    [ "$d" = yes ] && { install_wg; detect_wg; }
    [ "${#IF_CMD[@]}" -eq 0 ] && { warn "No interfaces yet."; $DRYRUN || die "create an interface, then re-run"; IF_CMD[awg0]=awg; IF_CONF[awg0]=/etc/amnezia/amneziawg/awg0.conf; }
  fi
  local names=("${!IF_CMD[@]}")
  if [ -n "$MANAGE_IFACES" ]; then IFS=',' read -ra SELECTED <<< "$MANAGE_IFACES"
  else
    echo "  Detected interfaces:"; local i=1; for n in "${names[@]}"; do echo "    $i) $n (${IF_CMD[$n]}) ${IF_CONF[$n]}"; i=$((i+1)); done
    local pick; read -rp "  Manage which? (comma indices, or 'all'): " pick </dev/tty || true; pick="${pick:-all}"
    if [ "$pick" = all ]; then SELECTED=("${names[@]}"); else SELECTED=(); IFS=',' read -ra idx <<< "$pick"; for j in "${idx[@]}"; do j="${j// /}"; [ -n "$j" ] && SELECTED+=("${names[$((j-1))]}"); done; fi
  fi
  for n in "${SELECTED[@]}"; do n="${n// /}"; [ -n "${IF_CMD[$n]:-}" ] || { [ -e "/etc/amnezia/amneziawg/$n.conf" ] && { IF_CMD[$n]=awg; IF_CONF[$n]="/etc/amnezia/amneziawg/$n.conf"; } || { IF_CMD[$n]=wg; IF_CONF[$n]="/etc/wireguard/$n.conf"; }; }; done
  ok "Managing: ${SELECTED[*]}"
}

[ "$(id -u)" = 0 ] || $DRYRUN || die "run as root (or use --dry-run)"
$DRYRUN && { info "DRY RUN — files render under ./dryrun, nothing executes."; rm -rf "$PREFIX"; }

ask "Panel URL (https://host:port)" "" PANEL_URL
ask "Node enrollment token (from the Nodes screen)" "" NODE_TOKEN
ask "Public IP clients dial for THIS node" "$ENDPOINT_IP" ENDPOINT_IP
[ -n "$PANEL_URL" ]  || $DRYRUN || die "PANEL_URL required — create the node in the panel's Nodes screen first"
[ -n "$NODE_TOKEN" ] || $DRYRUN || die "NODE_TOKEN required — copy it from the Nodes screen"
case "$PANEL_URL" in https://*) ;; *) warn "PANEL_URL is not https:// — the token would travel in clear. Continue only if you know why.";; esac
if [ -z "$TLS_VERIFY" ] && [ -z "$TLS_FINGERPRINT" ]; then
  ask_yn "Verify the panel's TLS certificate? (answer no if the panel uses a self-signed cert)" n TLS_VERIFY
fi
info "Checking wg/awg…"; choose_ifaces

# ───────────────────────── install binaries ─────────────────────────
info "Agent + daemon"
for f in swg-agent swg-noded; do [ -f "$SRC/$f" ] || die "missing $f beside this script (unzip the bundle here)"; done
mkdir -p "$PREFIX$AGENT_DIR" "$PREFIX$NODED_DIR"; cp "$SRC/swg-agent" "$PREFIX$AGENT_DIR/"; cp "$SRC/swg-noded" "$PREFIX$NODED_DIR/"
chmod 755 "$PREFIX$AGENT_DIR/swg-agent" "$PREFIX$NODED_DIR/swg-noded"; ok "installed agent + daemon"
mkdir -p "$PREFIX/var/lib/swg-noded" "$PREFIX/var/log/swg-agent" "$PREFIX/etc/swg-agent"

# ───────────────────────── config.json (pull-only HTTPS) ─────────────────────────
IFJSON=""; sep=""
for n in "${SELECTED[@]}"; do n="${n// /}"; [ -z "$n" ] && continue
  IFJSON+="$sep    \"$n\": { \"cmd\": [\"${IF_CMD[$n]}\"], \"conf\": \"${IF_CONF[$n]}\" }"; sep=$',\n'; done
VERIFY_JSON=$([ "$TLS_VERIFY" = yes ] && echo true || echo false)
FP=""; [ -n "$TLS_FINGERPRINT" ] && FP=$',\n    "fingerprint": "'"$TLS_FINGERPRINT"'"'
writef /etc/swg-agent/config.json 640 <<EOF
{
  "interfaces": {
$IFJSON
  },
  "endpoint_host": "${ENDPOINT_IP}",
  "dns": ["${DNS}"],
  "panel": {
    "url": "${PANEL_URL}",
    "token": "${NODE_TOKEN}",
    "verify": ${VERIFY_JSON}${FP}
  },
  "node": {
    "interval": ${INTERVAL},
    "agent": "${AGENT_DIR}/swg-agent",
    "sudo": false
  }
}
EOF
warn "config.json holds the node token (mode 640, root:root). Treat it as a secret."

# ───────────────────────── daemon service (root) ─────────────────────────
writef /etc/systemd/system/swg-noded.service 644 <<EOF
[Unit]
Description=swg-noded (HTTPS sync to panel) — ${ENDPOINT_IP}
After=network-online.target
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

# ───────────────────────── enable ─────────────────────────
info "Enable daemon"
run systemctl daemon-reload
run systemctl enable --now swg-noded

echo; ok "Node install complete — syncing to ${PANEL_URL} every ${INTERVAL}s."
echo
echo "It should turn green in the panel's Nodes screen within ~${INTERVAL}s."
echo "Logs:   journalctl -u swg-noded -f"
echo "Config: /etc/swg-agent/config.json"
[ "$VERIFY_JSON" = false ] && [ -z "$TLS_FINGERPRINT" ] && echo "TLS:    not verifying the panel cert (self-signed). To pin it instead, set TLS_FINGERPRINT to its sha256 and re-run."
$DRYRUN && { echo; ok "DRY RUN done — inspect ./dryrun"; }
