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
ensure_wg_tools(){ # ensure_wg_tools <awg|wg> — install tools + kernel module if missing (idempotent)
  local cmd="$1"
  if [ "$cmd" = wg ]; then have wg && return 0; run apt-get update -qq; run apt-get install -y wireguard
  else have awg && return 0; run apt-get update -qq; run apt-get install -y software-properties-common
       run add-apt-repository -y ppa:amnezia/ppa; run apt-get update -qq; run apt-get install -y amneziawg; fi
}
awg_obfuscation(){ # AmneziaWG v2 obfuscation — H1–H4 ranges, S1–S4, conservative QUIC-Initial I1
  local s1 s2 s3 s4 b1 b2 b3 b4 w=15
  s1=$(( 15 + RANDOM % 136 )); s2=$(( 15 + RANDOM % 136 ))
  while [ "$s1" -eq "$s2" ] || [ $((s1+56)) -eq "$s2" ]; do s2=$(( 15 + RANDOM % 136 )); done
  s3=$(( 15 + RANDOM % 86 )); s4=$(( 15 + RANDOM % 86 ))
  b1=$(( 5 + (RANDOM*RANDOM) % 900000000 ));          b2=$(( 1000000000 + (RANDOM*RANDOM) % 900000000 ))
  b3=$(( 2000000000 + (RANDOM*RANDOM) % 900000000 )); b4=$(( 3000000000 + (RANDOM*RANDOM) % 900000000 ))
  printf 'Jc = 4\nJmin = 40\nJmax = 70\nS1 = %s\nS2 = %s\nS3 = %s\nS4 = %s\nH1 = %s-%s\nH2 = %s-%s\nH3 = %s-%s\nH4 = %s-%s\n' \
    "$s1" "$s2" "$s3" "$s4" "$b1" $((b1+w)) "$b2" $((b2+w)) "$b3" $((b3+w)) "$b4" $((b4+w))
  printf 'I1 = <b 0xc300000001><r 1200>\n'   # QUIC v1 Initial prefix + random; no <c>/<t> (Android-safe)
}
server_addr(){ have python3 || die "python3 required for the tunnel address (also needed by the daemon)"
  python3 - "$1" <<'PY'
import ipaddress, sys
n = ipaddress.ip_network(sys.argv[1], strict=False)
print(f"{next(n.hosts())}/{n.prefixlen}")
PY
}
detect_wan(){ ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n1; }
create_iface(){ # prompt, gen server key, write conf (AWG v2 + QUIC I1, or plain WG), NAT it to the WAN, bring up, register
  local _proto proto name port subnet addr conf cmd priv dir wan up down
  ask "Protocol — (a)mneziawg or (w)ireguard?" "a" _proto; proto="${_proto:-a}"
  case "$proto" in w|wg|wireguard) proto=wg; cmd=wg; dir=/etc/wireguard;;
                                *) proto=awg; cmd=awg; dir=/etc/amnezia/amneziawg;; esac
  ask "Interface name" "$([ "$cmd" = awg ] && echo awg0 || echo wg0)" name
  ask "Listen port"    "51820" port
  ask "Tunnel subnet (CIDR; server takes the first host)" "10.8.0.0/24" subnet
  ask "WAN egress interface (clients are NAT'd out this)" "$(detect_wan || echo eth0)" wan
  addr="$(server_addr "$subnet")"; conf="$dir/$name.conf"; ensure_wg_tools "$cmd"
  up="sysctl -q -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -A FORWARD -i %i -o ${wan} -j ACCEPT; iptables -A FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  down="iptables -t nat -D POSTROUTING -s ${subnet} -o ${wan} -j MASQUERADE; iptables -D FORWARD -i %i -o ${wan} -j ACCEPT; iptables -D FORWARD -i ${wan} -o %i -m state --state RELATED,ESTABLISHED -j ACCEPT"
  printf 'net.ipv4.ip_forward = 1\n' | writef /etc/sysctl.d/99-swg-forward.conf 644
  run sysctl -q -w net.ipv4.ip_forward=1
  if $DRYRUN; then priv="<generated-on-real-run>"; else priv="$("$cmd" genkey)"; fi
  { printf '[Interface]\nPrivateKey = %s\nAddress = %s\nListenPort = %s\n' "$priv" "$addr" "$port"
    printf 'PostUp = %s\nPostDown = %s\n' "$up" "$down"
    [ "$cmd" = awg ] && awg_obfuscation; } | writef "$conf" 600
  if [ "$cmd" = awg ]; then run awg-quick up "$name"; run systemctl enable "awg-quick@$name"
  else                     run wg-quick  up "$name"; run systemctl enable "wg-quick@$name"; fi
  IF_CMD[$name]="$cmd"; IF_CONF[$name]="$conf"; ok "created $proto interface '$name' on :$port (server $addr, NAT out $wan)"
}
choose_ifaces(){
  detect_wg
  if [ "${#IF_CMD[@]}" -eq 0 ]; then
    warn "No wg/awg interface found."; local doit; ask_yn "Create one now? (installs wg/awg if needed)" y doit
    [ "$doit" = yes ] && create_iface
    [ "${#IF_CMD[@]}" -eq 0 ] && { $DRYRUN || die "create an interface, then re-run"; IF_CMD[awg0]=awg; IF_CONF[awg0]=/etc/amnezia/amneziawg/awg0.conf; }
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
