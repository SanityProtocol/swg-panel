#!/bin/sh
# swg-node entrypoint: bring up a userspace AmneziaWG interface, then run the
# HTTPS sync daemon. The panel manages peers declaratively; this box only needs
# its own server interface (mounted conf for obfuscation, or generated plain-WG).
set -eu
log(){ printf '\033[0;36m[swg-node]\033[0m %s\n' "$*"; }
rand32(){ od -An -N4 -tu4 /dev/urandom | tr -d ' '; }   # one unsigned 32-bit int

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
    {
      echo "[Interface]"
      echo "PrivateKey = $PRIV"
      echo "Address = ${NODE_ADDRESS:-10.8.0.1/24}"
      echo "ListenPort = ${NODE_LISTEN_PORT:-51820}"
      if [ "${NODE_PLAIN_WG:-no}" != yes ]; then
        s1=$(( 15 + $(rand32) % 136 )); s2=$(( 15 + $(rand32) % 136 ))
        while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + $(rand32) % 136 )); done
        s3=$(( 15 + $(rand32) % 86 )); s4=$(( 15 + $(rand32) % 86 ))
        b1=$(( 5 + $(rand32) % 900000000 ));          b2=$(( 1000000000 + $(rand32) % 900000000 ))
        b3=$(( 2000000000 + $(rand32) % 900000000 )); b4=$(( 3000000000 + $(rand32) % 900000000 ))
        printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
          "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+15)) "$b2" $((b2+15)) "$b3" $((b3+15)) "$b4" $((b4+15))
        printf 'I1 = <b 0xc300000001><r 1200>\n'   # conservative QUIC v1 Initial mimicry (no <c>/<t>)
      fi
    } > "$CONF"
    if [ "${NODE_PLAIN_WG:-no}" = yes ]; then
      log "generated a plain-WireGuard conf (unset NODE_PLAIN_WG for AmneziaWG v2 obfuscation)"
    else
      log "generated an AmneziaWG v2 conf with H1–H4 ranges (set NODE_PLAIN_WG=yes for plain WireGuard)"
    fi
  fi
fi
chmod 600 "$CONF"

# 2) bring the interface up in userspace (no kernel module in a container)
export WG_QUICK_USERSPACE_IMPLEMENTATION=amneziawg-go
log "bringing up $IFACE via userspace amneziawg-go"
awg-quick up "$IFACE" || { log "awg-quick up failed — check NET_ADMIN + /dev/net/tun"; exit 1; }

# 2b) NAT the tunnel subnet out the WAN (compose sets ip_forward + NET_ADMIN; we add the masquerade)
WAN="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1)"; WAN="${WAN:-eth0}"
SUBNET="$(python3 -c "import ipaddress,os;print(ipaddress.ip_network(os.environ.get('NODE_ADDRESS','10.8.0.1/24'),strict=False))" 2>/dev/null || echo 10.8.0.0/24)"
if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE 2>/dev/null; then :; else
  iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE \
    && log "NAT: masquerading $SUBNET out $WAN" \
    || log "WARNING: could not add MASQUERADE rule (need NET_ADMIN) — clients may have no internet"
fi

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
