#!/bin/sh
# swg-node entrypoint: bring up a userspace AmneziaWG interface, then run the
# HTTPS sync daemon. The panel manages peers declaratively; this box only needs
# its own server interface (mounted conf for obfuscation, or generated plain-WG).
set -eu
log(){ printf '\033[0;36m[swg-node]\033[0m %s\n' "$*"; }

: "${PANEL_URL:?PANEL_URL required (host-node: https://swg-panel:8443)}"
: "${NODE_TOKEN:?NODE_TOKEN required (create the node in the Nodes screen)}"
: "${NODE_ENDPOINT:?NODE_ENDPOINT required (public IP/host clients dial)}"
IFACE="${NODE_IFACE:-awg0}"
CONF="/etc/amnezia/amneziawg/${IFACE}.conf"
SRC_CONF="${CONF_SRC:-/etc/swg-node/${IFACE}.conf}"
mkdir -p /etc/amnezia/amneziawg /var/lib/swg-noded /etc/swg-agent

# 1) server interface conf: mounted source wins; else generate a plain-WireGuard one.
if [ ! -f "$CONF" ]; then
  if [ -f "$SRC_CONF" ]; then
    cp "$SRC_CONF" "$CONF"; log "using mounted interface conf ($SRC_CONF)"
  else
    PRIV="${SERVER_PRIVKEY:-$(awg genkey)}"
    { echo "[Interface]";
      echo "PrivateKey = $PRIV";
      echo "Address = ${NODE_ADDRESS:-10.8.0.1/24}";
      echo "ListenPort = ${NODE_LISTEN_PORT:-51820}"; } > "$CONF"
    log "generated a plain-WireGuard conf (mount $SRC_CONF for AmneziaWG obfuscation params)"
  fi
fi
chmod 600 "$CONF"

# 2) bring the interface up in userspace (no kernel module in a container)
export WG_QUICK_USERSPACE_IMPLEMENTATION=amneziawg-go
log "bringing up $IFACE via userspace amneziawg-go"
awg-quick up "$IFACE" || { log "awg-quick up failed — check NET_ADMIN + /dev/net/tun"; exit 1; }

# 3) swg-agent config: declarative HTTPS sync to the panel
VERIFY=false; [ "${TLS_VERIFY:-no}" = yes ] && VERIFY=true
FP=""; [ -n "${TLS_FINGERPRINT:-}" ] && FP=",
    \"fingerprint\": \"${TLS_FINGERPRINT}\""
cat > /etc/swg-agent/config.json <<JSON
{
  "interfaces": { "${IFACE}": { "cmd": ["awg"], "conf": "${CONF}" } },
  "endpoint_host": "${NODE_ENDPOINT}",
  "dns": ["${DNS:-1.1.1.1}"],
  "panel": {
    "url": "${PANEL_URL}",
    "token": "${NODE_TOKEN}",
    "verify": ${VERIFY}${FP}
  },
  "node": { "interval": ${INTERVAL:-5}, "agent": "/opt/swg-agent/swg-agent", "sudo": false }
}
JSON
chmod 600 /etc/swg-agent/config.json

# 4) sync loop: sample interface -> POST snapshot -> reconcile desired peers
log "syncing to ${PANEL_URL} (iface ${IFACE}, endpoint ${NODE_ENDPOINT})"
export SWG_AGENT_CONFIG=/etc/swg-agent/config.json SWG_NODED_STATE=/var/lib/swg-noded
exec /opt/swg-noded/swg-noded
