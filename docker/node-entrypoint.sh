#!/bin/sh
# swg-node entrypoint: bring up one or more userspace AmneziaWG interfaces, then run
# the HTTPS sync daemon. The panel manages peers declaratively; this box only needs
# its own server interface(s). Interfaces come from one of three sources:
#
#   1. mounted confs — every /etc/swg-node/*.conf (or CONF_SRC) is managed as-is
#      (the way to ship full AmneziaWG obfuscation; one file per interface);
#   2. NODE_IFACES spec — "name:port:address[:proto]" entries, comma-separated, each
#      generated (AmneziaWG v2 by default, ":wg" for plain WireGuard);
#   3. single fallback — NODE_IFACE / NODE_LISTEN_PORT / NODE_ADDRESS (back-compat).
#
# Publish each interface's UDP ListenPort in compose for the panel/clients to reach it.
set -eu
log(){ printf '\033[0;36m[swg-node]\033[0m %s\n' "$*"; }
rand32(){ od -An -N4 -tu4 /dev/urandom | tr -d ' '; }   # one unsigned 32-bit int

: "${PANEL_URL:?PANEL_URL required (host-node: https://swg-panel:8443)}"
: "${NODE_TOKEN:?NODE_TOKEN required (create the node in the Nodes screen)}"
: "${NODE_ENDPOINT:?NODE_ENDPOINT required (public IP/host clients dial)}"
AWG_DIR=/etc/amnezia/amneziawg
mkdir -p "$AWG_DIR" /var/lib/swg-noded /etc/swg-agent
MANAGED=""                                  # space-separated interface names
IFJSON=""; IFSEP=""                          # swg-agent interfaces map (built per-interface, with its endpoint)
add_iface(){ # add_iface <name> <endpoint>  — record an interface + its own endpoint for the config
  MANAGED="$MANAGED $1"
  IFJSON="$IFJSON$IFSEP    \"$1\": { \"cmd\": [\"awg\"], \"conf\": \"$AWG_DIR/$1.conf\", \"endpoint_host\": \"${2:-$NODE_ENDPOINT}\" }"
  IFSEP=",
"
}

# emit AmneziaWG v2 obfuscation params (H1–H4 ranges, S1–S4, conservative QUIC-Initial I1)
gen_awg_params(){
  s1=$(( 15 + $(rand32) % 136 )); s2=$(( 15 + $(rand32) % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + $(rand32) % 136 )); done
  s3=$(( 15 + $(rand32) % 86 )); s4=$(( 15 + $(rand32) % 86 ))
  b1=$(( 5 + $(rand32) % 900000000 ));          b2=$(( 1000000000 + $(rand32) % 900000000 ))
  b3=$(( 2000000000 + $(rand32) % 900000000 )); b4=$(( 3000000000 + $(rand32) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+15)) "$b2" $((b2+15)) "$b3" $((b3+15)) "$b4" $((b4+15))
  printf 'I1 = <b 0xc300000001><r 1200>\n'   # conservative QUIC v1 Initial mimicry (no <c>/<t>)
}

# gen_conf <name> <port> <address> <plain?yes|no>  — generate a server interface conf
gen_conf(){
  _name="$1"; _port="$2"; _addr="$3"; _plain="$4"; _dest="$AWG_DIR/$_name.conf"
  {
    echo "[Interface]"
    echo "PrivateKey = $(awg genkey)"
    echo "Address = $_addr"
    echo "ListenPort = $_port"
    echo "MTU = ${NODE_MTU:-1280}"   # headroom for turn-proxy obfuscation overhead
    [ "$_plain" = yes ] || gen_awg_params
  } > "$_dest"
  chmod 600 "$_dest"
  if [ "$_plain" = yes ]; then log "generated plain-WireGuard interface $_name on :$_port ($_addr)"
  else log "generated AmneziaWG v2 interface $_name on :$_port ($_addr)"; fi
}

# ───────── 1) source the interface set ─────────
if ls /etc/swg-node/*.conf >/dev/null 2>&1 || { [ -n "${CONF_SRC:-}" ] && [ -f "${CONF_SRC:-}" ]; }; then
  for src in /etc/swg-node/*.conf ${CONF_SRC:-}; do
    [ -f "$src" ] || continue
    name="$(basename "$src" .conf)"; dest="$AWG_DIR/$name.conf"
    [ -f "$dest" ] || cp "$src" "$dest"
    chmod 600 "$dest"; add_iface "$name" "$NODE_ENDPOINT"   # mounted confs carry no endpoint → node-level
    log "interface $name from mounted conf ($src)"
  done
elif [ -n "${NODE_IFACES:-}" ]; then
  # spec: name:port:address[:proto[:endpoint]]  (comma-separated). proto "wg" => plain WireGuard;
  # endpoint = the public IP/host clients dial for THIS interface (defaults to NODE_ENDPOINT).
  OIFS="$IFS"; IFS=','
  for entry in $NODE_IFACES; do
    IFS="$OIFS"
    name="$(echo "$entry" | cut -d: -f1)"
    port="$(echo "$entry" | cut -d: -f2)"; port="${port:-51820}"
    addr="$(echo "$entry" | cut -d: -f3)"; addr="${addr:-10.8.0.1/24}"
    proto="$(echo "$entry" | cut -d: -f4)"
    ep="$(echo "$entry" | cut -d: -f5)"; ep="${ep:-$NODE_ENDPOINT}"
    [ -n "$name" ] || { log "skipping malformed NODE_IFACES entry: $entry"; IFS=','; continue; }
    plain=no; [ "$proto" = wg ] && plain=yes
    [ -z "$proto" ] && [ "${NODE_PLAIN_WG:-no}" = yes ] && plain=yes
    if [ -f "$AWG_DIR/$name.conf" ]; then log "interface $name already present ($AWG_DIR/$name.conf)"
    else gen_conf "$name" "$port" "$addr" "$plain"; fi
    add_iface "$name" "$ep"; IFS=','
  done
  IFS="$OIFS"
else
  # single-interface fallback (back-compat)
  name="${NODE_IFACE:-awg0}"
  plain=no; [ "${NODE_PLAIN_WG:-no}" = yes ] && plain=yes
  if [ -f "$AWG_DIR/$name.conf" ]; then log "interface $name already present ($AWG_DIR/$name.conf)"
  else gen_conf "$name" "${NODE_LISTEN_PORT:-51820}" "${NODE_ADDRESS:-10.8.0.1/24}" "$plain"; fi
  add_iface "$name" "$NODE_ENDPOINT"
fi

[ -n "$MANAGED" ] || { log "no interfaces to manage"; exit 1; }

# ───────── 2) bring each up (userspace; no kernel module in a container) + NAT its subnet ─────────
export WG_QUICK_USERSPACE_IMPLEMENTATION=amneziawg-go
WAN="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1)"; WAN="${WAN:-eth0}"
NATTED=""                                   # subnets already masqueraded (dedupe)
for IFACE in $MANAGED; do
  dest="$AWG_DIR/$IFACE.conf"
  log "bringing up $IFACE via userspace amneziawg-go"
  awg-quick up "$IFACE" || { log "awg-quick up $IFACE failed — check NET_ADMIN + /dev/net/tun"; exit 1; }
  addr_line="$(awk -F= 'tolower($1) ~ /^[[:space:]]*address[[:space:]]*$/ {print $2; exit}' "$dest" | tr -d ' ' | cut -d, -f1)"
  SUBNET="$(python3 -c "import ipaddress,sys;print(ipaddress.ip_network(sys.argv[1],strict=False))" "$addr_line" 2>/dev/null || echo "")"
  [ -n "$SUBNET" ] || { log "WARNING: could not read subnet for $IFACE — skipping its NAT"; continue; }
  case " $NATTED " in *" $SUBNET "*) : ;; *)
    if iptables -t nat -C POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE 2>/dev/null; then :; else
      iptables -t nat -A POSTROUTING -s "$SUBNET" -o "$WAN" -j MASQUERADE \
        && log "NAT: masquerading $SUBNET out $WAN ($IFACE)" \
        || log "WARNING: could not add MASQUERADE for $SUBNET (need NET_ADMIN) — clients may have no internet"
    fi
    NATTED="$NATTED $SUBNET" ;;
  esac
done

# ───────── 3) swg-agent config: declarative HTTPS sync, all interfaces listed (with per-interface endpoints) ─────────
VERIFY=false; [ "${TLS_VERIFY:-no}" = yes ] && VERIFY=true
FP=""; [ -n "${TLS_FINGERPRINT:-}" ] && FP=",
    \"fingerprint\": \"${TLS_FINGERPRINT}\""
cat > /etc/swg-agent/config.json <<JSON
{
  "interfaces": {
$IFJSON
  },
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

# ───────── 4) sync loop: sample interfaces -> POST snapshot -> reconcile desired peers ─────────
log "syncing to ${PANEL_URL} (interfaces:${MANAGED}, endpoint ${NODE_ENDPOINT})"
export SWG_AGENT_CONFIG=/etc/swg-agent/config.json SWG_NODED_STATE=/var/lib/swg-noded
exec /opt/swg-noded/swg-noded
